from django.conf import settings

from ..objects.db import ObjectDatabase
from ..objects.types import DBObject
from .exceptions import MigrationError
from .config import DatacubeObjectConfig
from .manager import DatacubeObjectManager



class DatacubeObject(DBObject):
    """Base class for all Objects to be saved in a Dowell Datacube Database"""
    config_class = DatacubeObjectConfig
    manager_class = DatacubeObjectManager

    @classmethod
    def db(cls):
        """Returns the database client for the object class"""
        from .db import DatacubeDB
        db = super().db()
        if not isinstance(db, DatacubeDB):
            raise TypeError(f"db must be an instance of {DatacubeDB}")
        return db
    

    @classmethod
    def migrate(cls):
        """
        Creates the collection for the object class in the class manager's (Datacube) database.
        """
        if not cls.config:
            raise MigrationError("Cannot migrate an DBObject without a config. Define `cls.config`.")
        try:
            if cls.config.migrate:
                cls.db().create_collection(cls, dowell_api_key=settings.PROJECT_API_KEY)
        except Exception as exc:
            raise MigrationError(f"Failed to migrate {cls}") from exc
        return None
    

    @classmethod
    def flush(cls):
        """
        Deletes all documents/objects in the collection for the 
        object class in the class manager's (Datacube) database.
        """
        if not cls.config:
            raise MigrationError("Cannot flush an DBObject without a config. Define `cls.config`.")
        try:
            if cls.config.migrate:
                cls.db().flush_collection(cls, dowell_api_key=settings.PROJECT_API_KEY)
        except Exception as exc:
            raise MigrationError(f"Failed to flush {cls}") from exc
        return None
    

    def save(self, *, dowell_api_key: str, using: ObjectDatabase = None ,workspace_id: str = None, collection_name: str = None):
        """
        Saves the object to the database.

        :param dowell_api_key: The API key to use to connect to the database.
        :param using: The database to use. If not specified, the default database is used.
        :param workspace_id: The workspace ID  used to determine the collection name.
        """
        print("this is the workspace_id",workspace_id)
        collection_name = f"{workspace_id}_samantha_campaign" if workspace_id else collection_name
        
        print("First Save call", collection_name)
        return super().save(using=using, dowell_api_key=dowell_api_key, collection_name=collection_name)
    

    def delete(self, *, dowell_api_key: str,workspace_id:str, using: ObjectDatabase = None):
        """
        Deletes the object from the database.

        :param dowell_api_key: The API key to use to connect to the database.
        :param using: The database to use. If not specified, the default database is used.
        """

        
        print("First Delete call", workspace_id)
        return super().delete(using=using, dowell_api_key=dowell_api_key,workspace_id=workspace_id)


    async def asave(self, *, dowell_api_key: str, using: ObjectDatabase = None):
        """Asynchronous version of `save()`"""
        return super().asave(using=using, dowell_api_key=dowell_api_key)


    async def adelete(self, *, dowell_api_key: str, using: ObjectDatabase = None):
        """Asynchronous version of `delete()`"""
        return super().adelete(using=using, dowell_api_key=dowell_api_key)
