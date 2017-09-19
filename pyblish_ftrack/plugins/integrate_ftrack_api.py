import os

import pyblish.api
import clique


class PyblishFtrackIntegrateFtrackApi(pyblish.api.InstancePlugin):
    """ Commit components to server. """

    order = pyblish.api.IntegratorOrder
    label = "Ftrack"
    families = ["ftrack"]

    def query(self, entitytype, data):
        """ Generate a query expression from data supplied.

        If a value is not a string, we'll add the id of the entity to the
        query.

        Args:
            entitytype (str): The type of entity to query.
            data (dict): The data to identify the entity.
            exclusions (list): All keys to exclude from the query.

        Returns:
            str: String query to use with "session.query"
        """
        queries = []
        for key, value in data.iteritems():
            if not isinstance(value, (basestring, int)):
                if "id" in value.keys():
                    queries.append(
                        "{0}.id is \"{1}\"".format(key, value["id"])
                    )
            else:
                queries.append("{0} is \"{1}\"".format(key, value))

        query = (
            "select id from " + entitytype + " where " + " and ".join(queries)
        )
        self.log.debug(query)
        return query

    def process(self, instance):

        session = instance.context.data["ftrackSession"]
        task = instance.context.data["ftrackTask"]

        info_msg = "Created new {entity_type} with data: {data}"
        info_msg += ", metadata: {metadata}."

        # Iterate over components and publish
        for data in instance.data.get("ftrackComponentsList", []):

            # AssetType
            # Get existing entity.
            assettype_data = {"short": "upload"}
            assettype_data.update(data.get("assettype_data", {}))

            assettype_entity = session.query(
                self.query("AssetType", assettype_data)
            ).first()

            # Create a new entity if none exits.
            if not assettype_entity:
                assettype_entity = session.create("AssetType", assettype_data)
                self.log.info(
                    "Created new AssetType with data: ".format(assettype_data)
                )

            # Asset
            # Get existing entity.
            asset_data = {
                "name": task["name"],
                "type": assettype_entity,
                "parent": task["parent"],
            }
            asset_data.update(data.get("asset_data", {}))

            asset_entity = session.query(
                self.query("Asset", asset_data)
            ).first()

            # Extracting metadata, and adding after entity creation. This is
            # due to a ftrack_api bug where you can't add metadata on creation.
            asset_metadata = asset_data.pop("metadata", {})

            # Create a new entity if none exits.
            if not asset_entity:
                asset_entity = session.create("Asset", asset_data)
                self.log.info(
                    info_msg.format(
                        entity_type="Asset",
                        data=asset_data,
                        metadata=asset_metadata
                    )
                )

            # Adding metadata
            existing_asset_metadata = asset_entity["metadata"]
            existing_asset_metadata.update(asset_metadata)
            asset_entity["metadata"] = existing_asset_metadata

            # AssetVersion
            # Get existing entity.
            assetversion_data = {
                "version": 0,
                "asset": asset_entity,
                "task": task
            }
            assetversion_data.update(data.get("assetversion_data", {}))

            assetversion_entity = session.query(
                self.query("AssetVersion", assetversion_data)
            ).first()

            # Extracting metadata, and adding after entity creation. This is
            # due to a ftrack_api bug where you can't add metadata on creation.
            assetversion_metadata = assetversion_data.pop("metadata", {})

            # Create a new entity if none exits.
            if not assetversion_entity:
                assetversion_entity = session.create(
                    "AssetVersion", assetversion_data
                )
                self.log.info(
                    info_msg.format(
                        entity_type="AssetVersion",
                        data=assetversion_data,
                        metadata=assetversion_metadata
                    )
                )

            # Adding metadata
            existing_assetversion_metadata = assetversion_entity["metadata"]
            existing_assetversion_metadata.update(assetversion_metadata)
            assetversion_entity["metadata"] = existing_assetversion_metadata

            ## manage thumbnails
            thumbnail_path = data.get("thumbnail_path", "")
            if thumbnail_path and os.path.isfile(thumbnail_path):
                self.log.info(
                    'Got thumbnail: {0!r}.'.format(
                        thumbnail_path
                    )
                )
                thumbnail_component = assetversion_entity.create_thumbnail(thumbnail_path)
                self.log.info(thumbnail_component)
                if data.get("propagate_thumb_to_parents", False):
                    # we can use True for 1 and False for 0 or just an int above 1 to propagate through to the number of parents
                    # 1 is the task where the asset version is linked to
                    # 2 would be the parent of the task 
                    # 3 would be the parent of the parent of the task and so on
                    parent_count = data["propagate_thumb_to_parents"]
                    self.log.debug("propagating thumbnail")
                    entities = []
                    for item in task['link']:
                        entities.insert(0,session.get(item['type'], item['id']))
                    self.log.debug("found entities %s " % entities) 
                    for entity in entities[:parent_count]: 
                        if "thumbnail" in entity.keys():
                            self.log.info("found thumbnail field on %s propagating" % entity) 
                            entity["thumbnail"] = thumbnail_component
                        else:
                            continue
                    task.session.commit()
            else:
                self.log.info(
                    'Thumbnail file did not exist: {0!r}.'.format(
                        thumbnail_path
                    )
                )


            # Have to commit the version and asset, because location can't
            # determine the final location without.
            session.commit()

            # Component
            # Get existing entity.
            component_data = {
                "name": "main",
                "version": assetversion_entity
            }
            component_data.update(data.get("component_data", {}))

            component_entity = session.query(
                self.query("Component", component_data)
            ).first()

            component_overwrite = data.get("component_overwrite", False)
            location = data.get("component_location", session.pick_location())

            # Overwrite existing component data if requested.
            if component_entity and component_overwrite:

                origin_location = session.query(
                    "Location where name is \"ftrack.origin\""
                ).one()

                # Removing existing members from location
                components = list(component_entity.get("members", []))
                components += [component_entity]
                for component in components:
                    for loc in component["component_locations"]:
                        if location["id"] == loc["location_id"]:
                            location.remove_component(
                                component, recursive=False
                            )

                # Deleting existing members on component entity
                for member in component_entity.get("members", []):
                    session.delete(member)
                    del(member)

                session.commit()

                # Reset members in memory
                if "members" in component_entity.keys():
                    component_entity["members"] = []

                # Add components to origin location
                try:
                    collection = clique.parse(data["component_path"])
                except ValueError:
                    # Assume its a single file
                    # Changing file type
                    name, ext = os.path.splitext(data["component_path"])
                    component_entity["file_type"] = ext

                    origin_location.add_component(
                        component_entity, data["component_path"]
                    )
                else:
                    # Changing file type
                    component_entity["file_type"] = collection.format("{tail}")

                    # Create member components for sequence.
                    for member_path in collection:

                        size = 0
                        try:
                            size = os.path.getsize(member_path)
                        except OSError:
                            pass

                        name = collection.match(member_path).group("index")

                        member_data = {
                            "name": name,
                            "container": component_entity,
                            "size": size,
                            "file_type": os.path.splitext(member_path)[-1]
                        }

                        component = session.create(
                            "FileComponent", member_data
                        )
                        origin_location.add_component(
                            component, member_path, recursive=False
                        )
                        component_entity["members"].append(component)

                # Add components to location.
                location.add_component(
                    component_entity, origin_location, recursive=True
                )

                data["component"] = component
                msg = "Overwriting Component with path: {0}, data: {1}, "
                msg += "location: {2}"
                self.log.info(
                    msg.format(
                        data["component_path"],
                        component_data,
                        location
                    )
                )

            # Extracting metadata, and adding after entity creation. This is
            # due to a ftrack_api bug where you can't add metadata on creation.
            component_metadata = component_data.pop("metadata", {})

            # Create new component if none exists.
            new_component = False
            if not component_entity:
                component_entity = assetversion_entity.create_component(
                    data["component_path"],
                    data=component_data,
                    location=location
                )
                data["component"] = component_entity
                msg = "Created new Component with path: {0}, data: {1}"
                msg += ", metadata: {2}, location: {3}"
                self.log.info(
                    msg.format(
                        data["component_path"],
                        component_data,
                        component_metadata,
                        location
                    )
                )
                new_component = True

            # Adding metadata
            existing_component_metadata = component_entity["metadata"]
            existing_component_metadata.update(component_metadata)
            component_entity["metadata"] = existing_component_metadata

            # Setting assetversion thumbnail
            if data.get("thumbnail", False):
                assetversion_entity["thumbnail_id"] = component_entity["id"]

            # Inform user about no changes to the database.
            if (component_entity and not component_overwrite and
               not new_component):
                data["component"] = component_entity
                self.log.info(
                    "Found existing component, and no request to overwrite. "
                    "Nothing has been changed."
                )
            else:
                # Commit changes.
                session.commit()
