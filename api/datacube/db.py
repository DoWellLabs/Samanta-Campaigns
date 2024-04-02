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
        
        preferred_dbname = __type.config.preferred_db
        # print("preferred_dbname", preferred_dbname, self.name)
        datacube = DowellDatacube(db_name=preferred_dbname or self.name, dowell_api_key=dowell_api_key)
        collection =workspace_id.replace(" ", "")
        collection_name = f"{collection}_samantha_campaign"
        # print("collection_name", collection_name)
        try:
            _resp = datacube.fetch(_from=collection_name, limit=limit, offset=offset)
            # print(_resp)
            if wanted =="message":
               value = "campaign_id"
            elif wanted =="reports":
                value = "events"
            else:
                value = "creator_id"
            print(value)
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
        ):
        """
        Insert an object's data into the Datacube database based on its type.

        :param obj: The object whose data is to be inserted.
        :param dowell_api_key: The API key to use to access the Dowell Datacube API.
        :return: The object's data unique identifier in the database.
        """
        try:
            self._validate_object(obj)
            self._validate_api_key(dowell_api_key)
        except (TypeError, ValueError) as exc:
            raise InsertionError(
                f"Failed to insert object into the database"
            ) from exc
        preferred_dbname = obj.config.preferred_db
        datacube = DowellDatacube(db_name=preferred_dbname or self.name, dowell_api_key=dowell_api_key)
        # collection_name = collection_name
        # print("this is the collection_name", collection_name)
        document = obj.to_dbvalue()

        try:
            result = datacube.insert(_into=collection_name, data=document)
        except ConnectionError as exc:
            raise InsertionError(f"Failed to insert object into the database. {exc}")
        except CollectionNotFoundError as exc:
            raise InsertionError(f"Failed to insert object into the database. {exc}")
        except DatacubeError as exc:
            raise DatabaseError(f"Failed to insert object into the database. {exc}")
        
        document_id = result["inserted_id"]
        assert isinstance(document_id, str), f"Expected DowellDatacube.insert()['inserted_id'] to return a string, got {type(document_id)}"
        obj._pkey = document_id
        return document_id
        

    def update(
            self,
            obj,
            *,
            dowell_api_key: str,
            collection_name: str,
        ):
        """
        Update an object's data in the Datacube database.

        :param obj: The object whose data is to be updated.
        :param dowell_api_key: The API key to use to access the Dowell Datacube API.
        :param kwargs: Additional keyword arguments to pass to the Dowell Datacube client.
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

        preferred_dbname = obj.config.preferred_db
        datacube = DowellDatacube(db_name=preferred_dbname or self.name, dowell_api_key=dowell_api_key)
        new_document = obj.to_dbvalue()
        filter = {"_id": obj.pkey}
    

        try:
            datacube.update(_in=collection_name, filter=filter, data=new_document)
            return True
        except ConnectionError as exc:
            raise UpdateError(f"Failed to update object in the database. {exc}")
        except DatacubeError as exc:
            raise DatabaseError(f"Failed to update object in the database. {exc}")
    

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

        preferred_dbname = obj.config.preferred_db
        datacube = DowellDatacube(db_name=preferred_dbname or self.name, dowell_api_key=dowell_api_key)
        collection_name = f"{workspace_id}_samantha_campaign"

        try:
            datacube.delete(_from=collection_name, filter={"_id": obj.pkey})
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
