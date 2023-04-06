import time

import numpy as np
import pandas as pd
import requests

from todoist_analytics.frontend.colorscale import color_code_to_hex, color_to_hex


def get_completed(token: str, limit: int, offset: int):
    url = "https://api.todoist.com/sync/v9/completed/get_all"
    resp = requests.get(url, headers={
        "Authorization": f"Bearer {token}"
    },
                        params={
                            "limit": limit,
                            "offset": offset
                        })
    return resp.json()


def get_state(token):
    state_url = "https://api.todoist.com/sync/v9/sync"
    resp = requests.post(state_url, headers={
        "Authorization": f"Bearer {token}"
    },
                         data={
                             "sync_token": '*',
                             "resource_types": '["all"]'
                         })

    return resp.json()

class DataCollector:
    def __init__(self, token):
        self.token = token
        self.items = pd.DataFrame()
        self.projects = pd.DataFrame()
        self.current_offset = 0
        self.state = get_state(self.token)


    def get_user_timezone(self):
        self.tz = self.state["user"]["tz_info"]["timezone"]

    def _collect_active_tasks(self):
        pass

    def _collect_completed_tasks(self, limit, offset):
        data = get_completed(token=self.token,limit=limit, offset=offset)
        if data == "Service Unavailable\n":
            time.sleep(3)
            data = self._collect_completed_tasks(limit, offset)
        else:
            if len(data["items"]) != 0:
                self._append_to_properties(data)

    def _append_to_properties(self, data):
        preprocessed_items, preprocessed_projects = self._preprocess_completed_tasks(
            pd.DataFrame(data["items"]),
            pd.DataFrame.from_dict(data["projects"], orient="index"),
        )
        self.items = self.items.append(preprocessed_items)
        self.projects = self.projects.append(preprocessed_projects)

    def _collect_all_completed_tasks(self, limit=10_000):
        """
        gets all the tasks and stores it
        this function may take too long to complete and timeout,
        a limit is set in order to prevent this
        """
        stop_collecting = False
        old_shape = 0

        while not stop_collecting:
            self._collect_completed_tasks(limit=200, offset=self.current_offset)
            new_shape = self.items.shape[0]
            if new_shape != old_shape and new_shape < limit:
                old_shape = new_shape
                self.current_offset += 200
            else:
                self.current_offset = new_shape
                stop_collecting = True

    def _state_to_dataframe(self, state, key):
        f = pd.DataFrame.from_dict(state[str(key)])
        return f

    def _collect_active_tasks(self):
        self.active_tasks = self._state_to_dataframe(self.state, "items")
        keep_columns = [
            "checked",
            "content",
            "added_by_uid",
            "description",
            "due",
            "labels",
            "priority",
            "project_id",
            "added_at",
            "id",
        ]
        self.active_tasks = self.active_tasks[keep_columns]
        self.active_tasks = self.active_tasks.loc[self.active_tasks["checked"] == 0]

    def _preprocess_completed_tasks(self, completed_tasks, projects):
        projects = projects.rename({"id": "project_id"}, axis=1)

        completed_tasks["datehour_completed"] = pd.to_datetime(
            completed_tasks["completed_at"]
        )

        self.get_user_timezone()

        completed_tasks["datehour_completed"] = pd.DatetimeIndex(
            completed_tasks["datehour_completed"]
        ).tz_convert(self.tz)
        completed_tasks["completed_date"] = pd.to_datetime(
            completed_tasks["datehour_completed"]
        ).dt.date
        completed_tasks["completed_date_weekday"] = pd.to_datetime(
            completed_tasks["datehour_completed"]
        ).dt.day_name()
        completed_tasks = completed_tasks.merge(
            projects[["project_id", "name", "color"]],
            how="left",
            left_on="project_id",
            right_on="project_id",
        )
        completed_tasks = completed_tasks.rename({"name": "project_name"}, axis=1)

        # creating the recurrent flag column -> not good implementation
        completed_date_count = completed_tasks.groupby("task_id").agg(
            {"completed_date": "nunique"}
        )
        completed_date_count["isRecurrent"] = np.where(
            completed_date_count["completed_date"] > 1, 1, 0
        )
        completed_date_count.drop(columns="completed_date", inplace=True)

        completed_tasks = completed_tasks.merge(
            completed_date_count, left_on="task_id", right_index=True
        )

        completed_tasks["hex_color"] = completed_tasks["color"].apply(
            lambda x: color_to_hex[x]
        )

        completed_tasks = completed_tasks.drop_duplicates().reset_index(drop=True)

        return completed_tasks, projects
