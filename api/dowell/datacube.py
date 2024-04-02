from typing import Any, Dict,Optional
import requests

from .exceptions import (
    AlreadyExistsError, CollectionNotFoundError, DatacubeError, 
    ConnectionError, DatabaseNotFoundError
)



class DowellDatacube:
    """Dowell Datacube database client"""
    # Endpoints to connect to for the available database operations
    connection_urls = {
        "fetch": "https://datacube.uxlivinglab.online/db_api/get_data/",
        "insert": "https://datacube.uxlivinglab.online/db_api/crud/",
        "update": "https://datacube.uxlivinglab.online/db_api/crud/",
        "delete": "https://datacube.uxlivinglab.online/db_api/crud/",
        "add_collection": "https://datacube.uxlivinglab.online/db_api/add_collection/"
    }

    def __init__(self, db_name: str, *, dowell_api_key: str) -> None:
        """
        Creates a new Dowell Datacube client for the specified database.

        :param db_name: The name of the database to request connections to.
        :param dowell_api_key: Dowell user's API key that will be used to initiate database connections.
        """
        if not isinstance(db_name, str):
            raise TypeError("db_name must be a string")
        if not isinstance(dowell_api_key, str):
            raise TypeError("dowell_api_key must be a string")
        if not db_name:
            raise ValueError("db_name cannot be empty")
        if not dowell_api_key:
            raise ValueError("dowell_api_key cannot be empty")
        
        self.db_name = db_name
        self.api_key = dowell_api_key

    
    @property
    def connection_info(self):
        """Information about the datacube connection made by the client."""
        return {
            "db_name": self.db_name,
            "api_key": self.api_key,
        }

    
    def __repr__(self) -> str:
        return f"<DowellDatacube {self.db_name}>"


    def _handle_response_errors(self, response: requests.Response):
        """
        Handles errors in the connection response, if any. 
        Raises the appropriate exception for response error.
        """
        message = response.json().get("message", "")
        was_successful = response.json().get("success", False)
        if not was_successful or not response.ok:
            if 400 <= response.status_code < 500:
                if response.status_code == 404:
                    if "collection" in message.lower():
                        raise CollectionNotFoundError(message)
                    raise DatabaseNotFoundError(message)
                
                elif response.status_code == 409:
                    raise AlreadyExistsError(message)
                raise ConnectionError(f"Code{response.status_code} {message}")
            
            raise DatacubeError(f"Code{response.status_code} {message}")
        return None
    
    
    def fetch(
            self, 
            _from: str, 
            *,
            filters: Dict[str, Any] = {},
            limit: int = None,
            offset: int = None,
        ):
        """
        Initiates a new connection to retrieve all records from the specified collection of the database.

        :param _from: The name of the collection to fetch records from.
        :param filters: A dictionary of query filters to be used to filter the records to be retrieved.
        :param limit: The maximum number of records to retrieve.
        :param offset: The number of records to skip before retrieving the first record.
        :return: The connection response data.
        """
        if not isinstance(_from, str):
            raise TypeError("_from must be a string")
        if not _from:
            raise ValueError("_from cannot be empty")
        if not isinstance(filters, dict):
            raise TypeError("filters must be a dictionary")
        if limit:
            if not isinstance(limit, int):
                raise TypeError("limit must be an integer")
            if limit < 1:
                raise ValueError("limit can only be greater than or equal to 1")
        if offset:
            if not isinstance(offset, int):
                raise TypeError("offset must be an integer")
            if offset < 0:
                raise ValueError("offset can not be negative")
        operation = self.fetch.db_operation_name
        payload = {
            **self.connection_info,
            "coll_name": _from,
            "operation": operation,
            "filters": filters,
            "payment":False
        }
        if limit:
            payload["limit"] = limit
        if offset:
            payload["offset"] = offset

        # print("url is", self.connection_urls[operation])

        # print("json data is", payload)

        response = requests.post(url=self.connection_urls[operation], json=payload)
        # self._handle_response_errors(response)
        return response.json()["data"]
    

    def insert(self, _into: str, *, data: Dict[str, Any], filter: Optional[Dict[str, Any]] = None):
        print(_into)
        import time 
        
        start_time = time.time()
        """
        Initiates a new connection to create a new record in the specified collection of the database.

        :param _into: The name of the collection to create the record in.
        :param data: The data to be used to create the record.
        :param filter: Optional filter criteria.
        :return: The connection response data.
        """
        if not isinstance(_into, str):
            raise TypeError("_into must be a string")
        if not _into:
            raise ValueError("_into cannot be empty")
        if not isinstance(data, dict):
            raise TypeError("data must be a dictionary")
        if filter is not None and not isinstance(filter, dict):
            raise TypeError("filter must be a dictionary if provided")

        operation = self.insert.db_operation_name
        payload = {
            **self.connection_info,
            "coll_name": _into,
            "operation": operation,
            "data": data,
        }
        if filter:
            payload['filter'] = filter

        response = requests.post(url=self.connection_urls[operation], json=payload)
        self._handle_response_errors(response)
        
        end_time = time.time()
        
        print(f"Time took to insert to database: {end_time - start_time}")
        return response.json()["data"]
    

    def update(
            self, 
            _in: str, 
            *, 
            filter: Dict[str, Any] = {}, 
            data: Dict[str, Any]
        ):
        """
        Initiates a new connection to update the record that matches the given filter in the specified collection of the database.

        :param _in: The name of the collection that contains the record to be updated.
        :param filters: A dictionary containing a query filter to be used to identify the record to update in the collection.
        :param data: New data to update the record with.
        :return: The connection response data.
        """
        if not isinstance(_in, str):
            raise TypeError("_in must be a string")
        if not _in:
            raise ValueError("_in cannot be empty")
        if not isinstance(filter, dict):
            raise TypeError("filter must be a dictionary")
        if len(filter) != 1:
            raise ValueError("filter must have exactly one key-value pair")
        if not isinstance(data, dict):
            raise TypeError("data must be a dictionary")
        if not data:
            raise ValueError("data cannot be empty")
        operation = self.update.db_operation_name
        payload = {
            **self.connection_info,
            "coll_name": _in,
            "operation": operation,
            "query": filter,
            "update_data": data,
        }
        response = requests.put(url=self.connection_urls[operation], json=payload)
        self._handle_response_errors(response)
        return response.json()["data"]
    

    def delete(self, _from: str, *, filter: Dict[str, Any] = {}):
        """
        Initiates a new connection to delete the record that matches the given filter in the specified collection of the database.

        :param _from: The name of the collection that contains the record to be deleted.
        :param filters: A dictionary containing a query filter to be used to identify the record to delete in the collection.
        :return: The connection response data.
        """
        if not isinstance(_from, str):
            raise TypeError("_from must be a string")
        if not _from:
            raise ValueError("_from cannot be empty")
        if not isinstance(filter, dict):
            raise TypeError("filter must be a dictionary")
        if len(filter) != 1:
            raise ValueError("filter must have exactly one key-value pair")
        operation = self.delete.db_operation_name
        payload = {
            **self.connection_info,
            "coll_name": _from,
            "operation": operation,
            "query": filter,
        }
        response = requests.delete(url=self.connection_urls[operation], json=payload)
        self._handle_response_errors(response)
        return response.json()["data"]
    

    def create_collection(self, name: str, count: int = 1):
        """
        Initiates a new connection to create new collection(s) in the database.

        :param name: The name of the collection to create.
        :param count: The number of collections to create. Defaults to 1.
        :return: The connection response data.
        """
        # print("collection name is", name)
        if not isinstance(name, str):
            raise TypeError("name must be a string")
        if not isinstance(count, int):
            raise TypeError("count must be an integer")
        if not name:
            raise ValueError("name cannot be empty")
        if count < 1:
            raise ValueError("count must be greater than or equal to 1")
        operation = self.create_collection.db_operation_name
        payload = {
            **self.connection_info,
            "coll_names": name,
            "num_collections": count,
        }
        response = requests.post(url=self.connection_urls[operation], json=payload)
        self._handle_response_errors(response)
        return response.json()["data"]
    
    
    # Define the names of the database operations performed by the each method of the client
    fetch.db_operation_name = "fetch"
    insert.db_operation_name = "insert"
    update.db_operation_name = "update"
    delete.db_operation_name = "delete"
    create_collection.db_operation_name = "add_collection"


# db = DowellDatacube(db_name="Samantha_Campaigns", dowell_api_key="1b834e07-c68b-4bf6-96dd-ab7cdc62f07f")
# data = db.fetch(_from="CampaignMessage")
# for campaign in data:
#     db.delete(_from="CampaignMessage", filter={"_id": campaign["_id"]})
