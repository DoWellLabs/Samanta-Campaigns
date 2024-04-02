import datetime
from django.utils import timezone
import inspect
from typing import Any, Union
from dateutil import parser


from ..bases import Object, ObjectMeta
from ..utils import check_value_isinstance_of_given_types, import_obj_from_traversal_path
from ..config import DBObjectConfig
from ..signals import (
    pre_save, pre_delete, 
    post_save, post_delete
)
from ..exceptions import DatabaseError
from ..db import ObjectDatabase
from ..objectlist import ObjectList


def _prepare_dbobjects_in_value_for_db(value: Any):
    """
    Recursively searches for and converts all `DBObject`s in the given value to their database savable values.

    :param value: The value that may contain `DBObject`s to be prepared for the database.
    :return: The value with `DBObject`s converted to their database savable values.
    """
    if isinstance(value, DBObject):
        return value.to_dbvalue()
    
    elif isinstance(value, dict):
        for key, val in value.items():
            value[key] = _prepare_dbobjects_in_value_for_db(val)

    elif isinstance(value, (list, tuple, ObjectList)):
        # Convert all to list, a universal type.
        value = list(value)
        for i, val in enumerate(value):
            value[i] = _prepare_dbobjects_in_value_for_db(val)
    elif isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        value = value.isoformat()

    return value


def _construct_dbobjects_in_dbvalue(dbvalue: Any, primary_key: str):
    """
    Recursively searches for `DBObject`s in the given value and constructs them from their database values.
    The given value is assumed to be from the database.

    :param dbvalue: A database value that may contain `DBObject`s to be constructed from their database values.
    :param primary_key: The name of the primary key field in the database value.
    :return: The value with `DBObject`s constructed from their database values.
    """
    if isinstance(dbvalue, dict):
        if "__classloc__" in dbvalue:
            # If the database value has the class location, construct the DBObject from the database value
            try:
                dbobject_class: type[DBObject] = import_obj_from_traversal_path(dbvalue["__classloc__"])
                return dbobject_class.from_dbvalue(dbvalue, primary_key=primary_key)
            except:
                # If the DBObject cannot be constructed, return None
                return None
        else:
            for key, val in dbvalue.items():
                dbvalue[key] = _construct_dbobjects_in_dbvalue(val, primary_key=primary_key)

    elif isinstance(dbvalue, (list, tuple)):
        for i, val in enumerate(dbvalue):
            dbvalue[i] = _construct_dbobjects_in_dbvalue(val, primary_key=primary_key)

    return dbvalue


def _find_dbobjects_in_value(value: Any):
    """
    Recursively searches for `DBObject`s in the given value.

    :param value: The value that may contain `DBObject`s.
    :return: A list of `DBObject`s found in the value.
    """
    dbobjects = []
    if isinstance(value, DBObject):
        dbobjects.append(value)
    
    elif isinstance(value, dict):
        for val in value.values():
            dbobjects.extend(_find_dbobjects_in_value(val))

    elif isinstance(value, (list, tuple, ObjectList)):
        for val in value:
            dbobjects.extend(_find_dbobjects_in_value(val))
    return dbobjects


def _construct_timestamp_from_isofmt(
        isofmt: str, 
        expected_type: type[Union[datetime.datetime, datetime.date, datetime.time]] = datetime.datetime
    ):
    """
    Constructs a datetime, date or time from the given ISO formatted string.

    :param isofmt: The ISO formatted string.
    :param expected_type: The expected type of the timestamp. Defaults to `datetime.datetime`.
    :return: The constructed timestamp.
    """
    if expected_type == datetime.datetime:
        return parser.isoparse(isofmt)
    elif expected_type == datetime.date:
        return parser.isoparse(isofmt).date()
    elif expected_type == datetime.time:
        return parser.isoparse(isofmt).time()
    else:
        raise TypeError(f"Invalid type for expected_type: {expected_type}")



class SupportsDBOperations:
    """
    Mixin class for `Object`s that support database operations.
    """
    __supportsdb__ = True
    _db_supported_types = (
        list, tuple, dict, set, frozenset, str, int, float, bool, bytes, ObjectList,
        bytearray, type(None), datetime.datetime, datetime.date, datetime.time
    )

    @property
    def saved(self):
        """Returns True if the Object has been saved to the database."""
        return bool(self.pkey)

    @classmethod
    def db(cls) -> ObjectDatabase:
        """
        Returns the database used by the Object class' manager.
        """
        if not cls.manager:
            raise AttributeError(f"{cls} has no manager.")
        return cls.manager.get_db()

    
    @classmethod
    def from_dbvalue(cls, dbvalue: dict, primary_key: str = "pkey"):
        """
        Returns a new instance of the Object from the given database value.

        :param dbvalue: Dictionary representation of the Object from the database.
        :param primary_key: The name of the primary key field in the database value. Defaults to `pkey`.
        """
        cleaned = cls._clean_from_dbvalue(dbvalue, primary_key=primary_key)
        obj = cls(**cleaned)
        obj._pkey = cleaned[primary_key]
        return obj
    

    @classmethod
    def _clean_from_dbvalue(cls, dbvalue: dict, primary_key: str):
        """
        Cleans the given database value based on types defined in `config.attributes`.

        This is used when fetching the Object from the database.

        :param dbvalue: Dictionary representation of the Object from the database.
        :param primary_key: The name of the primary key field in the database value.
        :return: A dictionary representation of the Object with its attributes cleaned.
        """
        if not cls.config:
            raise AttributeError(f"{cls}.config is not defined")

        cleaned_dbvalue = {}
        for attr_name, allowed_attr_types in cls.config.attributes.items():
            # Get only the attributes defined in the Object's config
            if attr_name in dbvalue:
                attr_dbvalue = dbvalue[attr_name]
                try:
                    # Ensure that the attribute's database value is an instance of at least one of the database supported types
                    check_value_isinstance_of_given_types(
                        valuename=attr_name, 
                        value=attr_dbvalue, 
                        types=cls._db_supported_types
                    )
                except TypeError as exc:
                    raise TypeError(f"Invalid database value for attribute '{attr_name}' of {cls}: {exc}")
                
                # Search for and construct all DBObjects in the value from their database values
                attr_dbvalue = _construct_dbobjects_in_dbvalue(attr_dbvalue, primary_key=primary_key)
                for attr_type in allowed_attr_types:
                    # Try to convert the attribute's database value to its corresponding attribute type
                    # to ensure that the correct data type for the attribute is returned
                    try:
                        if issubclass(attr_type, ObjectList):
                            # Get the class of the ObjectList's items
                            dbobjects = _find_dbobjects_in_value(attr_dbvalue)
                            if dbobjects:
                                obj_cls = dbobjects[0].__class__
                                # Construct the ObjectList from the database value
                                objlist = attr_type(object_class=obj_cls, objects=attr_dbvalue)
                                cleaned_dbvalue[attr_name] = objlist
                                break

                        elif issubclass(attr_type, (datetime.datetime, datetime.date, datetime.time)):
                            # Construct the datetime from the database value and break out of the loop
                            cleaned_dbvalue[attr_name] = _construct_timestamp_from_isofmt(attr_dbvalue, attr_type)
                            break

                        if attr_dbvalue is not None:
                            # Convert the attribute's database value to the attribute type
                            cleaned_dbvalue[attr_name] = attr_type(attr_dbvalue)
                            # if successful, break out of the loop else try the next type
                        else:
                            # If the attribute's database value is None, set the attribute's value to None
                            cleaned_dbvalue[attr_name] = attr_dbvalue
                        break
                    except (ValueError, TypeError):
                        # If the conversion fails, try the next type
                        continue
                    
        # Add the primary key to the cleaned_dbvalue, if it exists
        cleaned_dbvalue[primary_key] = dbvalue.get(primary_key, None)
        return cleaned_dbvalue


    def to_dbvalue(self):
        """
        Returns a dictionary representation of the Object to be saved in the database.

        This is used when saving the Object to the database.
        """
        if not self.config:
            raise AttributeError(f"{self}.config is not defined")
        prepared_dbvalue = self._prepare_to_dbvalue()
        return prepared_dbvalue
    

    def _prepare_to_dbvalue(self):
        """
        Returns a database savable representation of the Object.

        This is used in `to_dbvalue()` method.
        """
        if not self.config:
            raise AttributeError(f"{self}.config is not defined")
        
        prepared_dbvalue = {}
        for attr_name in self.config.attributes.keys():
            # Get the value of the attribute on the Object
            obj_attr_val = getattr(self, attr_name)
            try:
                # Ensure that the attribute's value is an instance of at least one of the database supported types
                check_value_isinstance_of_given_types(
                    valuename=attr_name, 
                    value=obj_attr_val, 
                    types=self._db_supported_types
                )
            except TypeError as exc:
                raise TypeError(f"Attribute of {self}, {exc}")
            # Convert all DBObjects in the attribute's value to their database savable values
            prepared_dbvalue[attr_name] = _prepare_dbobjects_in_value_for_db(obj_attr_val)

        # Add the class' location to prepared_dbvalue value so that it can be used to reconstruct the object later.
        class_location = f"{self.__class__.__module__}.{self.__class__.__name__}"
        prepared_dbvalue_with_class_location = {
            **prepared_dbvalue,
            "__classloc__": class_location,
        }
        return prepared_dbvalue_with_class_location

    
    def save(self, *args, **kwargs):
        """Saves the Object to the database."""
        raise NotImplementedError(f"{self.__class__} does not support saving. Method `save` must be implemented.")

    def delete(self, *args, **kwargs):
        """Deletes the Object from the database."""
        raise NotImplementedError(f"{self.__class__} does not support deleting. Method `delete` must be implemented.")

    async def asave(self, *args, **kwargs):
        """Asynchronous version of `save`."""
        raise NotImplementedError(f"{self.__class__} does not support saving. Method `asave` must be implemented.")

    async def adelete(self, *args, **kwargs):
        """Asynchronous version of `delete`."""
        raise NotImplementedError(f"{self.__class__} does not support deleting. Method `adelete` must be implemented.")

    @classmethod
    def migrate(cls, *args, **kwargs):
        """Migrates the Object class to the database."""
        raise NotImplementedError(f"{cls} does not support migrating. Method `migrate` must be implemented.")

    @classmethod
    def flush(cls, *args, **kwargs):
        """Deletes all Objects of the class from the database."""
        raise NotImplementedError(f"{cls} does not support flushing. Method `flush` must be implemented.")



class DBObjectMeta(ObjectMeta):
    def __new__(cls, name, bases, attrs):
        new_class = super().__new__(cls, name, bases, attrs)
        # Ensure that the `migrate` method implemented in the new class and its superclasses, is a classmethod
        new_class_mro = new_class.mro()
        # Arrange the MRO in reverse order so that the parent class attributes are overridden 
        # by the child class attributes in 'class_dict_aggregate'
        new_class_mro.reverse()

        class_dict_aggregate = {}
        for class_ in new_class_mro:
            class_dict_aggregate.update(getattr(class_, "__dict__", {}))

        migrate_method= class_dict_aggregate.get("migrate", None)
        flush_method = class_dict_aggregate.get("flush", None)
        for method_name, method in (("migrate", migrate_method), ("flush", flush_method)):
            if method:
                is_classmethod = not inspect.ismethod(method) and isinstance(method, classmethod)
                if not is_classmethod:
                    raise TypeError(f"'{method_name}()' method must be a classmethod.")
        
        # Add the new class to the list of supported types for database operations
        new_class._db_supported_types = (*new_class._db_supported_types, new_class)
        return new_class
    


class DBObject(SupportsDBOperations, Object, metaclass=DBObjectMeta):
    """
    Base class for `Object`s that can interact with the database via the client provided by the Object's manager.

    A mapping of the Object's attributes to the attribute type should be defined in `config.attributes`.
    Other default sub-configurations available are defined in the Object's `config_class`.

    The following class attributes can be defined in subclasses to customize the Object:
        - `config_class`: These can be used to specify a custom configuration class for the Object.
        This class must be a subclass of `ObjectConfig`. If not specified, the default configuration class is used.

        - `config`: An instance of the `config_class`. This is used to configure the Object's attributes.
        Call the `new_config` classmethod to get a new instance of the `config_class`.

        - `manager`: An instance of the `ObjectManager` class. This is used to manage the Object.
        A new instance of the `ObjectManager` class is automatically created for the Object if this is not specified.
    
    Create a simple Book Object class that can be saved to the database as follows:
    ```
    class Book(DBObject):
        # Get a new configuration for the Book Object class
        config = DBObject.new_config()
        config.attributes = {
            "title": str,
            "author": str,
            "year": str,
            "is_published": bool
        }
        config.required = ("title", "author", "year")
        config.defaults = {
            "is_published": False,
        }
        config.ordering = ("title", "-year", "author")
        config.validators = {
            "title": [is_not_blank, MinMaxLengthValidator(min_length=3, max_length=255).validate],
            "author": [is_not_blank, MinMaxLengthValidator(min_length=3, max_length=255).validate],
            "year": [is_not_blank, MinMaxLengthValidator(min_length=4, max_length=4).validate],
        }
    
    # Create a new Book
    book = Book(title="The Great Gatsby", author="F. Scott Fitzgerald", year="1925")
    # Save the Book to the database
    book.save()
    # OR
    book = Book.manager.create(title="The Great Gatsby", author="F. Scott Fitzgerald", year="1925")
    # Check that book is saved to the database
    print(book.pkey) # Prints the unique identifier of the Book in the database

    # Get details of the Book
    print(book.data)
    # Delete the Book from the database
    book.delete()

    # Fetch all Books from the database
    books = Book.manager.all()
    ```
    """
    config_class = DBObjectConfig

    def _validate_using(self, using: ObjectDatabase):
        """Ensures that the database is an instance of the Object's manager's base database class."""
        if not isinstance(using, self.manager_class.base_db_class):
            raise TypeError(f"Expected {self.manager_class.base_db_class}, got {type(using)}")
        return using
    
    
    def save(self, *, using: ObjectDatabase = None, collection_name: str, **kwargs):
        """
        Saves the Object to the database.

        :param using: The database to use for insert operation. Defaults to `self.db()`.
        :param collection_name: The name of the collection to save the object to.
        :param kwargs: keyword arguments to pass to database on save.
        """
        
        # print("my collection",collection_name)
        import time

        start_time = time.time()
        using = using or self.db()
        if not using:
            raise ValueError("No database client found.")
        using = self._validate_using(using)
        
        pre_save.send(sender=self.__class__, instance=self, using=using)
        # Update auto_now_datetimes to current datetime before saving
        for attr in self.config.auto_now_datetimes:
            setattr(self, attr, timezone.now())
            
        self.run_validations() # Run validations before saving
        if not self.pkey: # If the Object does not have a primary key, it has not been saved to the database yet
            # print("FOR INSERT", collection_name)
            pk = using.insert(self,collection_name=collection_name, **kwargs)
            if not pk:
                raise DatabaseError("An error occurred while saving the Object to the database. Primary key was not returned.")
            self._pkey = str(pk)
        else:
            saved = using.update(self, collection_name=collection_name, **kwargs)
            if not isinstance(saved, bool):
                raise DatabaseError("An error occurred while saving the Object to the database. Result was not a boolean.")
            if not saved:
                raise DatabaseError("An error occurred while saving the Object to the database.")
            
        post_save.send(sender=self.__class__, instance=self, using=using)
        
        end_time = time.time()
        
        print(f"Time taken to save last call: {end_time - start_time} seconds")
        return self
    

    def delete(self, *, using: ObjectDatabase = None,workspace_id:str=None, **kwargs):
        """
        Deletes the Object from the database.

        :param using: The database to use for delete operation. Defaults to `self.db()`.
        :param kwargs: keyword arguments to pass to database on deletion.
        """
        using = using or self.db()
        if not using:
            raise ValueError("No database client found.")
        using = self._validate_using(using)

        pre_delete.send(sender=self.__class__, instance=self, using=using)
        deleted = using.delete(self,workspace_id=workspace_id, **kwargs)

        if not isinstance(deleted, bool):
            raise DatabaseError("An error occurred while deleting the Object from the database. Result was not a boolean.")
        if not deleted:
            raise DatabaseError("Object was not deleted from the database.")
        
        post_delete.send(sender=self.__class__, instance=self, using=using)
        del self
        return None
    
    
    async def asave(self, *, using: ObjectDatabase = None, **kwargs):
        """
        Saves the Object to the database asynchronously.

        :param using: The database to use for insert operation. Defaults to the `self.db()`.
        :param kwargs: keyword arguments to pass to database on save.
        """
        return self.save(using=using, **kwargs)
    
    
    async def adelete(self, *, using: ObjectDatabase = None, **kwargs):
        """
        Deletes the Object from the database asynchronously.

        :param using: The database to use for delete operation. Defaults to the `self.db()`.
        :param kwargs: keyword arguments to pass to database on deletion.
        """
        return self.delete(using=using, **kwargs)

