import functools
import inspect
import asyncio
from django.conf import settings

from .objectlist import ObjectList
from .db import ObjectDatabase
from .utils import import_obj_from_traversal_path




class ObjectManager:
    """
    Base ObjectManager from which all ObjectManagers inherit. 
    An object manager is used to interact with and manage Objects.

    This manager cannot be instantiated directly and cannot be used 
    without an objectlist class.
    Create a useable subclass using any of the below methods:

    First;
    ```python
    from objects.objectlist import ObjectList
    from objects.manager import ObjectManager, use_objectlist
    ```
    Method 1:
    ```python
    class MyObjectList(ObjectList):
        ...
        def my_method(self):
            ...

    @use_objectlist(MyObjectList)
    class MyObjectManager(ObjectManager):
        ...

    manager = MyObjectManager(*args, **kwargs)
    ```
    Read the docstring of the `use_objectlist` decorator for more information.

    Method 2:
    ```python
    class MyObjectList(ObjectList):
        ...
        def my_method(self):
            ...
    
    class MyObjectManager(ObjectManager.from_objectlist(MyObjectList)):
        ...
    
    manager = MyObjectManager(*args, **kwargs)
    ```

    Method 3:
    ```python
    MyObjectManager = ObjectManager.from_objectlist(MyObjectList, subclass_name="MyObjectManager")

    manager = MyObjectManager(*args, **kwargs)
    ```
    Read the docstring of the `from_objectlist` classmethod for more information.

    The following class attributes can be modified to customize the manager's behavior:
        - `base_objectlist_class`: The objectlist class used by the `ObjectManager` subclass be a subclass of this class.
        The manager can only be used with the objectlist class defined on this attribute.
        - `base_db_class`: The database used by the `ObjectManager` subclass must be an instance of this class.
        Also, the manager's `db` attribute must be an instance of this class.
        - `base_object_class`: The object class attribute of the `ObjectManager` subclass must be a subclass of this class.
        The manager `object_class` attribute must be a subclass of this class.
        - `object_class`: The type of `Object`s that the manager will be managing. 
        This attribute is set automatically when the subclass is created using `for_objectclass()`.
        - `db`: The preferred database to be used by the manager. If not provided, the default database set in `settings.DEFAULT_OBJECT_DATABASE_CLASS` is used.
        Use the `get_db()` method to get the database currently used by the manager.

    By default, all ObjectManagers use a dummy database. Any direct instance of `ObjectDatabase` is considered a dummy database. 
    To use a real database, create a subclass of `ObjectDatabase` and override the existing methods in the class to return the right type of data.
    Implement your preferred database logic in the overridden methods. Then, set the ObjectManager's `db` attribute to an instance of the subclass.
    #### P.S: To know the right type of data to return, check the docstrings of the `ObjectDatabase` class or of its methods.
    """
    base_objectlist_class = ObjectList
    base_db_class = ObjectDatabase
    base_object_class = None

    object_class = None
    db = base_db_class(name="dummy_db")

    def __init__(self, *args, **kwargs):
        self._constructor_args = (args, kwargs)
        if self.__class__ == ObjectManager:
            raise TypeError(
                f"{self.__class__} cannot be instantiated directly. "
                f"Please use {self.__class__.__name__}.from_objectlist() "
                f"or {self.__class__.__name__}.for_objectclass()"
                " to create an instantiable subclass."
            )
        self._check_manager_ok()
        return None
        

    def _check_manager_ok(self):
        """Ensures that the manager is set up correctly."""
        if not issubclass(self.base_objectlist_class, ObjectList):
            raise TypeError(
                f"{self.__name__}.base_objectlist_class must be a subclass of {ObjectList}, not {self.base_objectlist_class}"
            )
        if not issubclass(self.base_db_class, ObjectDatabase):
            raise TypeError(
                f"{self.__name__}.base_db_class must be a subclass of {ObjectDatabase}, not {self.base_db_class}"
            )
        if self.db and not isinstance(self.db, self.base_db_class):
            raise TypeError(
                f"{self.__name__}.db must be an instance of {self.base_db_class}, not {self.db.__class__}"
            )
        
        # If object_class is set, and if base_object_class is set, check that object_class is set correctly.
        if self.base_object_class:
            if self.object_class and not issubclass(self.object_class, self.base_object_class):
                raise TypeError(
                    f"{self.__name__}.object_class must be a subclass of {self.base_object_class}, not {self.object_class}"
                )
        return None
    
    
    @classmethod
    def get_default_db_class(cls):
        """
        Returns the default database class as defined in `settings.DEFAULT_OBJECT_DATABASE_CLASS`.
        """
        default_db_cls = None
        default_db_path = getattr(settings, "DEFAULT_OBJECT_DATABASE_CLASS", None)
        if default_db_path:
            try:
                default_db_cls = import_obj_from_traversal_path(default_db_path)
                if not inspect.isclass(default_db_cls):
                    raise AttributeError(f"settings.DEFAULT_OBJECT_DATABASE_CLASS must be a class, not {default_db_cls}")
                
            except (ImportError, AttributeError) as exc:
                raise ImportError(
                    f"Could not import '{default_db_path}' in settings.DEFAULT_OBJECT_DATABASE_CLASS"
                ) from exc
        
        if default_db_cls and not issubclass(default_db_cls, cls.base_db_class):
            raise TypeError(
                f"settings.DEFAULT_OBJECT_DATABASE_CLASS must be a subclass of {cls.base_db_class}, not {default_db_cls}."
            )
        return default_db_cls


    @classmethod
    def set_db(cls, db: base_db_class):
        """
        Set database to be used by the manager class.

        :param db: An instance of `base_db_class` or its subclass.
        """
        if not isinstance(db, cls.base_db_class):
            raise TypeError(f"db must be an instance of {cls.base_db_class}.")
        cls.db = db
        return None 
    
    
    @classmethod
    def get_db(cls):
        """Returns the database used by the manager class."""
        # If cls.db is not set, or cls.db's is a direct instance of ObjectDatabase(Meaning its using a dummy database),
        # Try to get the default database class defined in settings.py. If defined, return an instance of it.
        if not cls.db or cls.db.__class__ == ObjectDatabase:
            default_db_class = cls.get_default_db_class()
            if default_db_class:
                # If a default database was provided in settings.py, use it.
                return default_db_class()
            
        if not isinstance(cls.db, cls.base_db_class):
            raise TypeError(f"{cls.__name__}.db must be an instance of {cls.base_db_class}, not {cls.db.__class__}")
        return cls.db
        

    @classmethod
    def from_objectlist(
            cls, 
            objectlist_class: type[ObjectList], 
            *, 
            using: ObjectDatabase = None, 
            subclass_name: str = None
        ) -> type["ObjectManager"]:
        """
        Creates a subclass of the ObjectManager for the given ObjectList class/subclass.

        :param objectlist_class: The ObjectList for which to create the subclass.
        :param using: The database to be used by the subclass.
        :param subclass_name: The name to create subclass with. 
        Defaults to `"{cls.__name__}From{objectlist_class.__name__}"`.
        """
        if not subclass_name:
            subclass_name = f"{cls.__name__}From{objectlist_class.__name__}"
        # Create a subclass of ObjectManager for the given objectlist class.
        object_manager_subclass = type(
            subclass_name,
            (cls,),
            {
            "   db": using or cls.get_db(),
            },
        )

        objectlist_setter_class = getattr(cls, "objectlist_setter_class", None)
        if objectlist_setter_class and not issubclass(objectlist_setter_class, use_objectlist):
            raise TypeError(
                f"{cls.__name__}.objectlist_setter_class must be a subclass of {use_objectlist}, not {cls.use_objectlist}"
            )
        if not objectlist_setter_class:
            objectlist_setter_class = use_objectlist

        # Create a setter for the objectlist class
        objectlist_setter = objectlist_setter_class(objectlist_class)
        # Update the manager subclass to use the given objectlist class using the objectlist list setter
        object_manager_subclass = objectlist_setter(object_manager_subclass)
        return object_manager_subclass


    @classmethod
    def for_objectclass(
            cls, 
            object_class, 
            *, 
            using: ObjectDatabase = None, 
            subclass_name: str = None
        ):
        """
        Creates a subclass of the ObjectManager for the given Object class/subclass.
        
        :param object_class: The Object class for which to create the subclass.
        :param using: The database to be used by the subclass.
        :param subclass_name: The name to create subclass with. Defaults to `"{object_class.__name__}Manager"`.
        """
        if not subclass_name:
            subclass_name = f"{object_class.__name__}Manager"

        # If no objectlist class is set for this manager, use the base objectlist class to create a subclass.
        manager_objectlist_class = getattr(cls, "_objectlist_class", None) or cls.base_objectlist_class
        objectlist_subclass_for_object = type(
            f"{object_class.__name__}List",
            (manager_objectlist_class,),
            {}
        )
        # Create a subclass of ObjectManager for the ObjectList subclass.
        object_manager_subclass = cls.from_objectlist(objectlist_subclass_for_object, using=using, subclass_name=subclass_name)
        # Update the ObjectManager subclass to use the given object class.
        object_manager_subclass.object_class = object_class
        return object_manager_subclass


    def get_objectlist(self) -> base_objectlist_class:
        """
        Returns an instance of the objectlist class for the manager.
        """
        if not getattr(self, "_objectlist_class", None):
            raise AttributeError(
                f"{self.__class__} does not have an objectlist class. "
                "Please create a useable subclass of the ObjectManager class"
                " using the 'from_objectlist()' or 'for_objectclass()' classmethods."
            )
        return self._objectlist_class(object_class=self.object_class, using=self.get_db())


    def __repr__(self):
        return f"<{self.__class__.__name__} ({self.__hash__()})>"


    def create(self, *, save: bool = True, **kwargs):
        """
        Creates an Object with the specified attributes. 
        Saves it to the database and returns it (if it supports database operations)

        :param save: If `True`, the Object is saved to the database after creation.
        :param kwargs: keyword arguments of the form `attribute=value` to be used to create the Object.
        :returns: the created `Object`.
        """
        import time
        
        start_time = time.time()
        obj = self.object_class(**kwargs)
        if save and obj.supports_db:
            obj.save()
            
        end_time = time.time()
        
        print("Actually create call", start_time, end_time)
        return obj
    
    
    def get_or_create(self, **kwargs):
        """
        Returns an Object that matches the specified attributes or creates one if it does not exist.

        :param kwargs: keyword arguments of the form `attribute=value` to be used to get or create the Object.
        :returns: a tuple of the form `(Object, created)`, where `Object` is the retrieved or created Object and `created` is a boolean specifying whether a new Object was created.
        """
        try:
            return self.get(**kwargs), False
        except self.object_class.DoesNotExist:
            return self.create(**kwargs), True
    

    def update(self, **kwargs):
        """
        Updates the attributes of all Objects of the manager with the specified attributes.

        :param kwargs: keyword arguments of the form `attribute=value` to be used to update the Objects.
        """
        updated_objs = []
        for obj in self.all():
            for key, value in kwargs.items():
                setattr(obj, key, value)
            updated_objs.append(obj)
        return self.bulk_save(*updated_objs)


    def bulk_save(self, *objs, using: ObjectDatabase = None, **kwargs):
        """
        Saves Objects given to the database.
        Can be a useful way to save a large number of objects in a single call.

        :param objs: Objects to be saved.
        :param using: The database to save the Objects in.
        :param kwargs: keyword arguments to be passed to the `save()` method of the Objects on save.
        """
        asyncio.run(self.abulk_save(*objs, using=using, **kwargs))


    async def abulk_save(self, *objs, using: ObjectDatabase = None, **kwargs):
        """
        Saves all Objects provided as arguments to the database asynchronously.
        
        :param using: The database to save the Objects in.
        :param objs: Objects to be saved.
        :param kwargs: keyword arguments to be passed to the `save()` method of the Objects on save.
        """
        if not objs:
            raise ValueError("No objects provided.")
        
        if not all([isinstance(obj, self.object_class) for obj in objs]):
            raise TypeError(
                f"All objects must be instances of {self.object_class}"
            )
        
        tasks = [ obj.asave(using=using, **kwargs) for obj in objs if obj.supports_db ]
        if tasks:
            await asyncio.gather(*tasks)
        return None



class use_objectlist:
    """ 
    Class for creating decorators that updates an `ObjectManger` subclass 
    to use the given ObjectList class or subclass, and adds manager equivalents 
    of the public methods of the given objectlist class.
    """

    def __init__(self, objectlist_class: type[ObjectList], *, set_as_base: bool = False):
        """
        Create a decorator that updates the decorated `ObjectManger` subclass 
        to use the given ObjectList class or subclass, and adds manager equivalents 
        of the public methods of the given objectlist class.

        :param objectlist_class: The `ObjectList` class/subclass the manager should use.
        :param set_as_base: If `True`, the ObjectList class/subclass is set as the 
        manager's `base_objectlist_class`.

        Example:
        ```python
        from objects.objectlist import ObjectList
        from objects.manager import ObjectManager, use_objectlist

        class MyObjectList(ObjectList):
            ...
            def my_method(self):
                ...

        @use_objectlist(MyObjectList)
        class MyObjectManager(ObjectManager):
            ...
        ```
        Note that this is not this not the same as:

        ```python
        class MyObjectManager(ObjectManager.from_objectlist(MyObjectList)):
            ...
        ```
        
        The latter creates a subclass of `ObjectManager` that is inherited by `MyObjectManager` .
        The subclass created uses `MyObjectList` as its objectlist class.
        The former updates `MyObjectManager` class (directly) to use `MyObjectList` as its objectlist class.

        Customize how the manager equivalent of the objectlist methods are created by 
        overriding the `make_manager_method()` method.
        """
        self.objectlist_class = objectlist_class
        self.set_as_base = set_as_base
    

    def __call__(self, manager_subclass: type[ObjectManager]):
        """
        #### `ObjectManager` subclass decorator.

        Updates an `ObjectManager` subclass to use the given `ObjectList` class or subclass, 
        and adds manager equivalents of the public methods of the given objectlist class.

        :param manager_subclass: The `ObjectManager` subclass to update.
        """
        if not issubclass(manager_subclass, ObjectManager):
            raise TypeError(
                f"{self.__class__.__name__} must be used on an ObjectManager subclass, not {manager_subclass}"
            )
        if not issubclass(self.objectlist_class, manager_subclass.base_objectlist_class):
            raise TypeError(
                f"{self.objectlist_class} must be a subclass of {manager_subclass.base_objectlist_class}."
            )
        
        if not hasattr(manager_subclass, "get_objectlist") and inspect.isfunction(manager_subclass.get_objectlist):
            raise NotImplementedError(
                f"{manager_subclass.__name__} must have a 'get_objectlist()' method."
            )

        missing_methods = self.get_missing_methods(self.objectlist_class, manager_subclass)
        for method_name, method in missing_methods.items():
            manager_method = self.make_manager_method(method_name)
            manager_method = functools.wraps(method)(manager_method)
            setattr(manager_subclass, method_name, manager_method)

        manager_subclass._objectlist_class = self.objectlist_class
        if self.set_as_base:
            manager_subclass.base_objectlist_class = self.objectlist_class

        # Set the manager class' `objectlist_setter_class` attribute
        manager_subclass.objectlist_setter_class = self.__class__
        return manager_subclass
    

    def get_objectlist_methods(self, objectlist_class: type[ObjectList]):
        """
        Returns a dictionary containing the objectlist class' public methods 
        that have the attribute `objectlist_only=False.`

        :param objectlist_class: The ObjectList class to get methods from.
        """
        objectlist_methods = {}
        for name, method in inspect.getmembers(
            objectlist_class, 
            predicate=inspect.isfunction
        ):
            # Only copy public methods or methods with the attribute
            # objectlist_only=False.
            objectlist_only = getattr(method, "objectlist_only", False)
            if objectlist_only is True or name.startswith("_"):
                continue
            # Copy the method onto the manager.
            objectlist_methods[name] = method
        return objectlist_methods

    
    def get_missing_methods(self, objectlist_class: type[ObjectList], manager_subclass: type[ObjectManager]):
        """
        Returns a dictionary of ObjectList methods that are not available on the manager class.

        :param objectlist_class: The ObjectList class to get methods from.
        :param manager_subclass: The manager subclass to check against.
        :returns: A dictionary of ObjectList methods that are not available on the manager class.
        """
        objectlist_methods = self.get_objectlist_methods(objectlist_class)
        missing_methods = {}
        for method_name, method in objectlist_methods.items():
            if hasattr(manager_subclass, method_name):
                continue
            missing_methods[method_name] = method
        return missing_methods
    

    def make_manager_method(self, method_name: str):
        """
        Creates a manager method for the given objectlist method name.

        Override this method to customize the manager method creation process.

        :param method_name: Name of the objectlist method.
        :returns: The manager method.
        """
        def manager_method(self, *args, **kwargs):
            print("Fourth check for GET")
            return getattr(self.get_objectlist(), method_name)(*args, **kwargs)
        return manager_method
    