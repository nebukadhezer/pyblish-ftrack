import os
import json
import base64
import sys
import ftrack

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import pyblish_ftrack_utils

import pyblish.api


@pyblish.api.log
class CollectFtrackData(pyblish.api.Selector):
    """Collects ftrack data from FTRACK_CONNECT_EVENT
        Arguments:
            version (int): version number of the publish
    """

    order = pyblish.api.Selector.order + 0.11
    hosts = ['*']
    version = (0, 1, 0)

    def process_context(self, context):

        decodedEventData = json.loads(
            base64.b64decode(
                os.environ.get('FTRACK_CONNECT_EVENT')
            )
        )

        taskid = decodedEventData.get('selection')[0]['entityId']
        ftrack_data = pyblish_ftrack_utils.getData(taskid)

        # Get ftrack Asset
        task = ftrack.Task(taskid)

        shot = ftrack.Shot(id=ftrack_data['Shot']['id'])

        asset_type = ftrack_data['Task']['code']
        asset_name = ftrack_data['Task']['type']

        assets = task.getAssets(assetTypes=[asset_type])

        if assets:
            for a in assets:
                if a.getName() == asset_name:
                    self.log.info('Found existing asset with name {}'.format(a.getName()))
                    asset = a
                    break
                else:
                    self.log.info('Found existing asset with name {}'.format(a.getName()))
                    asset = a
        else:
            self.log.info('Creating new asset')
            asset = shot.createAsset(name=asset_name, assetType=asset_type, task=task)

        self.log.info('Using ftrack asset {}'.format(asset.getName()))

        ftrack_data['Asset'] = {'id': asset.getId(),
                                'name': asset.getName()
                                }

        # Get ftrack AssetVersion or set 'createFtrackVersion' argument
        if context.data('version'):
            version_number = int(context.data('version'))
            version = None

            for v in asset.getVersions():
                if int(v.getVersion()) == version_number:
                    version = v
                    ftrack_data['AssetVersion'] = {'id': version.getId(),
                                                   'number': version_number,
                                                   }
                    self.log.warning('This version already exists. Will check for existence of  components')

            if not version:
                context.set_data('createFtrackVersion', value=True)
                self.log.debug('Setting createFtrackVersion arguments')
        else:
            context.set_data('createFtrackVersion', value=True)
            self.log.debug('Setting createFtrackVersion arguments')
            self.log.warning('Missing version number in context.')

        # set ftrack data
        self.log.debug('ftrackData: \n' + str(ftrack_data))
        context.set_data('ftrackData', value=ftrack_data)

        self.log.info('Found ftrack data')