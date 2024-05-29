from concurrent.futures import ThreadPoolExecutor
from django.conf import settings

from ..dowell.datacube import DowellDatacube
from ..objects.db import ObjectDatabase
from ..dowell.exceptions import (
    ConnectionError, DatacubeError, 
    CollectionNotFoundError
)
from .exceptions import (
    DatabaseError, FetchError,
    InsertionError, UpdateError, DeletionError
)

import concurrent.futures



class DatacubeDB(ObjectDatabase):
    """A Datacube Database client."""
    name = None

    def __init__(self, name: str = None):
        """
        Create a new DatacubeDB instance.

        :param name: The name of the Datacube database to use. 
        This must be the name of an existing Datacube database.
        """
        name = name or self.name
        super().__init__(name)

    
    def _validate_api_key(self, dowell_api_key: str):
        if not isinstance(dowell_api_key, str):
            raise TypeError(f"dowell_api_key must be a string")
        if not dowell_api_key:
            raise ValueError(f"dowell_api_key cannot be empty")
        return None
    

    def _validate_object_type(self, __type):
        from .objects import DatacubeObject
        if not issubclass(__type, DatacubeObject):
            raise TypeError(f"__type must be a subclass of {DatacubeObject}")
        if not __type.config:
            raise ValueError(f"{__type} 'config' attribute is not set.")
        return None
    

    def _validate_object(self, obj):
        from .objects import DatacubeObject
        if not isinstance(obj, DatacubeObject):
            raise TypeError(f"obj must be an instance of {DatacubeObject}")
        return None
    

    def fetch(
            self, 
            __type, 
            *,
            dowell_api_key: str, 
            limit: int = None,
            offset: int = None,
            workspace_id: str = None,
            wanted: str = None,
        ):
        """
        Retrieve objects of the specified type from the Datacube database.

        :param __type: The type of the objects to retrieve. Must be a subclass of DatacubeObject.
        :param dowell_api_key: The API key to use to access the Dowell Datacube API.
        :param limit: The maximum number of objects to retrieve.
        :param offset: The number of objects to skip before retrieving objects.
        :return: A generator that yields objects of the specified type.
        """
        try:
            self._validate_object_type(__type)
            self._validate_api_key(dowell_api_key)
        except (TypeError, ValueError) as exc:
            raise FetchError(
                f"Failed to fetch objects from the database"
            ) from exc
        
        preferred_dbname = f"{workspace_id}_samanta_campaign_db"
        # print("preferred_dbname", preferred_dbname, self.name)
        datacube = DowellDatacube(db_name=preferred_dbname or self.name, dowell_api_key=dowell_api_key)
        collection =workspace_id.replace(" ", "")
        collection_name = f"{collection}_campaign_details"
        print("collection_name", collection_name)
        print("this is wanted",wanted)
        try:
            _resp = datacube.fetch(_from=collection_name, limit=limit, offset=offset)
            if wanted =="message":
               value = "sender"
            elif wanted =="reports":
                value = "events"
            else:
                value = "creator_id"
            print(value)
            print("testing vim")
            documents = [obj for obj in _resp if obj.get(value)]
        except ConnectionError as exc:
            raise FetchError(f"Failed to fetch objects from the database. {exc}")
        except CollectionNotFoundError as exc:
           
            raise FetchError(f"Failed to fetch objects from the database. {exc}")
        except DatacubeError as exc:
            raise DatabaseError(f"Failed to fetch objects from the database. {exc}")
        
        assert isinstance(documents, list), f"Expected DowellDatacube.fetch() to return a list, got {type(documents)}"

        # Generator approach was used to avoid loading all objects into memory at once. 
        # Which could affect performance if the number of documents returned is large.
        for document in documents:
            assert isinstance(document, dict), f"Expected DowellDatacube.fetch() to return a list of dicts, got {type(document)}"
            yield __type.from_dbvalue(document, primary_key="_id")
            
        

    def insert(
        self, 
        obj, 
        *,
        dowell_api_key: str,
        collection_name: str,
        max_workers: int = 20  # Increase the number of worker threads
    ):
        """
        Insert an object's data into the Datacube database based on its type.

        :param obj: The object whose data is to be inserted.
        :param dowell_api_key: The API key to use to access the Dowell Datacube API.
        :param max_workers: The maximum number of worker threads for concurrent insertions.
        :return: The object's data unique identifier in the database.
        """
        try:
            self._validate_object(obj)
            self._validate_api_key(dowell_api_key)
        except (TypeError, ValueError) as exc:
            raise InsertionError(
                f"Failed to insert object into the database"
            ) from exc

        # Extract workspace_id from collection_name
        workspace_id = collection_name.split('_samantha')[0]
        print("this is workspace_id", workspace_id)
        preferred_dbname = f"{workspace_id}_samanta_campaign_db"
        datacube = DowellDatacube(db_name=preferred_dbname or self.name, dowell_api_key=dowell_api_key)
        document = obj.to_dbvalue()
        print("this is document", document)
        final_collection = f"{workspace_id}_campaign_details"

        try:
            result = datacube.insert(_into=final_collection, data=document)
        except ConnectionError as exc:
            raise InsertionError(f"Failed to insert object into the database. {exc}")
        except CollectionNotFoundError as exc:
            raise InsertionError(f"Failed to insert object into the database. {exc}")
        except DatacubeError as exc:
            raise DatabaseError(f"Failed to insert object into the database. {exc}")
        
        document_id = result["inserted_id"]
        assert isinstance(document_id, str), f"Expected DowellDatacube.insert()['inserted_id'] to return a string, got {type(document_id)}"
        obj._pkey = document_id

        # Extract audiences and leads_links only if creator_id exists in the document
        if 'creator_id' in document:
            audiences = document.get('audiences', [])
            leads_links = document.get('leads_links', [])
            creator_id = document['creator_id']
            print("this is audiences", audiences)
            print("this is leads_links", leads_links)

            email_collection_name = f"{workspace_id}_emails"
            link_collection_name = f"{workspace_id}_links"

            # Add creator_id and campaign_id to each audience and link
            for audience in audiences:
                audience['creator_id'] = creator_id
                audience['campaign_id'] = document_id

            for leads_link in leads_links:
                leads_link['creator_id'] = creator_id
                leads_link['campaign_id'] = document_id

            # Function to insert data
            def insert_data(collection_name, data):
                try:
                    datacube.insert(_into=collection_name, data=data)
                    print(f"Inserted data: {data}")
                except ConnectionError as exc:
                    raise InsertionError(f"Failed to insert data into the database. {exc}")
                except CollectionNotFoundError as exc:
                    raise InsertionError(f"Failed to insert data into the database. {exc}")
                except DatacubeError as exc:
                    raise DatabaseError(f"Failed to insert data into the database. {exc}")

            # Use concurrent.futures to insert data concurrently
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = []
                for audience in audiences:
                    futures.append(executor.submit(insert_data, email_collection_name, audience))
                for leads_link in leads_links:
                    futures.append(executor.submit(insert_data, link_collection_name, leads_link))
                
                # Wait for all futures to complete
                for future in concurrent.futures.as_completed(futures):
                    try:
                        future.result()
                    except Exception as exc:
                        raise InsertionError(f"Failed to insert data concurrently into the database. {exc}")

        return document_id


    def update(
        self,
        obj,
        *,
        dowell_api_key: str,
        collection_name: str,
        max_workers: int = 20  # Increase the number of worker threads
    ):
        """
        Update an object's data in the Datacube database.

        :param obj: The object whose data is to be updated.
        :param dowell_api_key: The API key to use to access the Dowell Datacube API.
        :param max_workers: The maximum number of worker threads for concurrent updates.
        :return: True if the object's data was updated successfully, False otherwise.
        """
        try:
            self._validate_object(obj)
            if not obj.pkey:
                raise UpdateError(f"object has no primary key yet. Cannot update object in the database.")
            self._validate_api_key(dowell_api_key)
        except (TypeError, ValueError) as exc:
            raise UpdateError(
                f"Failed to update object in the database"
            ) from exc

        # Extract workspace_id from collection_name
        workspace_id = collection_name.split('_samantha')[0]
        print("this is workspace_id", workspace_id)
        preferred_dbname = f"{workspace_id}_samanta_campaign_db"
        datacube = DowellDatacube(db_name=preferred_dbname or self.name, dowell_api_key=dowell_api_key)

        new_document = obj.to_dbvalue()
        final_collection = f"{workspace_id}_campaign_details"

        filter = {"_id": obj.pkey}

        try:
            datacube.update(_in=final_collection, filter=filter, data=new_document)
        except ConnectionError as exc:
            raise UpdateError(f"Failed to update object in the database. {exc}")
        except CollectionNotFoundError as exc:
            raise UpdateError(f"Failed to update object in the database. {exc}")
        except DatacubeError as exc:
            raise DatabaseError(f"Failed to update object in the database. {exc}")

        # Extract audiences and leads_links only if creator_id exists in the document
        if 'creator_id' in new_document:
            audiences = new_document.get('audiences', [])
            leads_links = new_document.get('leads_links', [])
            creator_id = new_document['creator_id']

            email_collection_name = f"{workspace_id}_emails"
            link_collection_name = f"{workspace_id}_links"

            # Function to update data
            def update_data(collection_name, data):
                data_filter = {"id": data["id"]}
                try:
                    datacube.update(_in=collection_name, filter=data_filter, data=data)
                except ConnectionError as exc:
                    raise UpdateError(f"Failed to update data in the database. {exc}")
                except CollectionNotFoundError as exc:
                    raise UpdateError(f"Failed to update data in the database. {exc}")
                except DatacubeError as exc:
                    raise DatabaseError(f"Failed to update data in the database. {exc}")

            # Use concurrent.futures to update data concurrently
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = []
                for audience in audiences:
                    audience['creator_id'] = creator_id
                    audience['campaign_id'] = filter["_id"]
                    futures.append(executor.submit(update_data, email_collection_name, audience))
                
                for leads_link in leads_links:
                    leads_link['creator_id'] = creator_id
                    leads_link['campaign_id'] = filter["_id"]
                    futures.append(executor.submit(update_data, link_collection_name, leads_link))
                
                # Wait for all futures to complete
                for future in concurrent.futures.as_completed(futures):
                    try:
                        future.result()
                    except Exception as exc:
                        raise UpdateError(f"Failed to update data concurrently in the database. {exc}")

        return True

    def delete(
            self,
            obj,
            *,
            dowell_api_key: str,
            workspace_id: str,
        ):
        """
        Delete an object's data from the Datacube database.

        :param obj: The object whose data is to be deleted.
        :param dowell_api_key: The API key to use to access the Dowell Datacube API.
        :return: True if the object's data was deleted successfully, False otherwise.
        """
        try:
            self._validate_object(obj)
            if not obj.pkey:
                raise DeletionError(f"object has no primary key yet. Cannot delete object from the database.")
            self._validate_api_key(dowell_api_key)
        except (TypeError, ValueError) as exc:
            raise DeletionError(
                f"Failed to delete object from the database"
            ) from exc

        preferred_dbname = f"{workspace_id}_samanta_campaign_db"
        datacube = DowellDatacube(db_name=preferred_dbname or self.name, dowell_api_key=dowell_api_key)
        collection_name = f"{workspace_id}_campaign_details"

        try:
            datacube.delete(_from=collection_name, filter={"_id": obj.pkey})
            datacube.delete(_from=f"{workspace_id}_links",filter={"campaign_id":obj.pkey})
            datacube.delete(_from=f"{workspace_id}_emails",filter={"campaign_id":obj.pkey})
            return True
        except ConnectionError as exc:
            raise DeletionError(f"Failed to delete object from the database. {exc}")
        except DatacubeError as exc:
            raise DatabaseError(f"Failed to delete object from the database. {exc}")
    

    def create_collection(
            self,
            __type,  
            *,
            dowell_api_key: str,
        ):
        """
        Create a collection in the Datacube database for the specified object type.

        :param __type: The type of the objects to create a collection for. Must be a subclass of DatacubeObject.
        :param dowell_api_key: The API key to use to access the Dowell Datacube API.
        :return: True if the collection was created successfully, False otherwise.
        """
        try:
            self._validate_object_type(__type)
            self._validate_api_key(dowell_api_key)
        except (TypeError, ValueError) as exc:
            raise DatabaseError(
                f"Failed to create collection in the database"
            ) from exc

        preferred_dbname = __type.config.preferred_db
        datacube = DowellDatacube(db_name=preferred_dbname or self.name, dowell_api_key=dowell_api_key)        
        collection_name = __type.config.collection_name

        try:
            datacube.create_collection(name=collection_name)
            return True
        except DatacubeError as exc:
            raise DatabaseError(f"Failed to create collection in the database. {exc}")

    
    def flush_collection(
            self,
            __type,
            *,
            dowell_api_key: str,
        ):
        """
        Delete all objects of the specified type from their Datacube database collection.

        :param __type: The type of the objects to delete. Must be a subclass of DatacubeObject.
        :param dowell_api_key: The API key to use to access the Dowell Datacube API.
        :return: True if the collection was flushed successfully, False otherwise.
        """
        dbobjects = self.fetch(__type, dowell_api_key=dowell_api_key)
        with ThreadPoolExecutor() as executor:
            futures = []
            for dbobject in dbobjects:
                futures.append(executor.submit(self.delete, dbobject, dowell_api_key=dowell_api_key))
            for future in futures:
                future.result()
        return True
