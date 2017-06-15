import os
import json
import base64

from ftrack_connect.session import get_shared_session
import pyblish.api


class PyblishFtrackCollectFtrackApi(pyblish.api.ContextPlugin):
    """ Collects an ftrack session and the current task id. """

    order = pyblish.api.CollectorOrder
    label = "Ftrack"

    def process(self, context):

        # Collect session
        session = get_shared_session()
        context.data["ftrackSession"] = session

        # Collect task
        taskid = ""
        try:
            decodedEventData = json.loads(
                base64.b64decode(
                    os.environ.get("FTRACK_CONNECT_EVENT")
                )
            )

            taskid = decodedEventData.get("selection")[0]["entityId"]
        except:
            taskid = os.environ.get("FTRACK_TASKID", "")

        context.data["ftrackTask"] = session.get("Task", taskid)
