"""Client.py
Client is the Python public API for TerminusDB"""
import base64
import copy
import gzip
import json
import os
import urllib.parse as urlparse
import warnings
from collections.abc import Iterable
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

import requests

from ..__version__ import __version__
from ..errors import DatabaseError, InterfaceError
from ..woql_utils import (
    _clean_dict,
    _dt_dict,
    _dt_list,
    _finish_response,
    _result2stream,
    _args_as_payload,
)
from ..woqlquery.woql_query import WOQLQuery

# client object
# license Apache Version 2
# summary Python module for accessing the Terminus DB API


class WoqlResult:
    """Iterator for streaming WOQL results."""
    def __init__(self, lines):
        preface = json.loads(next(lines))
        if not ('@type' in preface and preface['@type'] == 'PrefaceRecord'):
            raise DatabaseError(response=preface)
        self.preface = preface
        self.postscript = {}
        self.lines = lines

    def _check_error(self, document):
        if ('@type' in document):
            if document['@type'] == 'Binding':
                return document
            if document['@type'] == 'PostscriptRecord':
                self.postscript = document
                raise StopIteration()

        raise DatabaseError(response=document)

    def variable_names(self):
        return self.preface['names']

    def __iter__(self):
        return self

    def __next__(self):
        return self._check_error(json.loads(next(self.lines)))


class JWTAuth(requests.auth.AuthBase):
    """Class for JWT Authentication in requests"""

    def __init__(self, token):
        self._token = token

    def __call__(self, r):
        r.headers["Authorization"] = f"Bearer {self._token}"
        return r


class APITokenAuth(requests.auth.AuthBase):
    """Class for API Token Authentication in requests"""

    def __init__(self, token):
        self._token = token

    def __call__(self, r):
        r.headers["Authorization"] = f"Token {self._token}"
        return r


class Patch:
    def __init__(self, json=None):
        if json:
            self.from_json(json)
        else:
            self.content = None

    @property
    def update(self):
        def swap_value(swap_item):
            result_dict = {}
            for key, item in swap_item.items():
                if isinstance(item, dict):
                    operation = item.get("@op")
                    if operation is not None and operation == "SwapValue":
                        result_dict[key] = item.get("@after")
                    elif operation is None:
                        result_dict[key] = swap_value(item)
            return result_dict

        return swap_value(self.content)

    @update.setter
    def update(self):
        raise Exception("Cannot set update for patch")

    @update.deleter
    def update(self):
        raise Exception("Cannot delete update for patch")

    @property
    def before(self):
        def extract_before(extract_item):
            before_dict = {}
            for key, item in extract_item.items():
                if isinstance(item, dict):
                    value = item.get("@before")
                    if value is not None:
                        before_dict[key] = value
                    else:
                        before_dict[key] = extract_before(item)
                else:
                    before_dict[key] = item
            return before_dict

        return extract_before(self.content)

    @before.setter
    def before(self):
        raise Exception("Cannot set before for patch")

    @before.deleter
    def before(self):
        raise Exception("Cannot delete before for patch")

    def from_json(self, json_str):
        content = json.loads(json_str)
        if isinstance(content, dict):
            self.content = _dt_dict(content)
        else:
            self.content = _dt_list(content)

    def to_json(self):
        return json.dumps(_clean_dict(self.content))

    def copy(self):
        return copy.deepcopy(self)


class GraphType(str, Enum):
    """Type of graph"""
    INSTANCE = 'instance'
    SCHEMA = 'schema'


class Client:
    """Client for TerminusDB server.

    Attributes
    ----------
    server_url : str
        URL of the server that this client connected.
    api : str
        API endpoint for this client.
    team : str
        Team that this client is using. "admin" for local dbs.
    db : str
        Database that this client is connected to.
    user : str
        TerminiusDB user that this client is using. "admin" for local dbs.
    branch : str
        Branch of the database that this client is connected to. Default to "main".
    ref : str, None
        Ref setting for the client. Default to None.
    repo : str
        Repo identifier of the database that this client is connected to. Default to "local".
    """

    def from_json(self, json_str):
        content = json.loads(json_str)
        if isinstance(content, dict):
            self.content = _dt_dict(content)
        else:
            self.content = _dt_list(content)

    def to_json(self):
        return json.dumps(_clean_dict(self.content))

    def __init__(
        self,
        server_url: str,
        user_agent: str = f"terminusdb-client-python/{__version__}",
        **kwargs,
    ) -> None:
        r"""The Client constructor.

        Parameters
        ----------
        server_url : str
            URL of the server that this client will connect to.
        user_agent : optional, str
            User agent header when making requests. Defaults to terminusdb-client-python with the version appended.
        **kwargs
            Extra configuration options

        """
        self.server_url = server_url.strip("/")
        self.api = f"{self.server_url}/api"
        self._connected = False

        # properties with get/setters
        self._team = None
        self._db = None
        self._user = None
        self._branch = None
        self._ref = None
        self._repo = None
        self._references = {}

        # Default headers
        self._default_headers = {"user-agent": user_agent}

    @property
    def team(self):
        if isinstance(self._team, str):
            return urlparse.unquote(self._team)
        else:
            return self._team

    @team.setter
    def team(self, value):
        if isinstance(value, str):
            self._team = urlparse.quote(value)
        else:
            self._team = value

    @property
    def db(self):
        if isinstance(self._db, str):
            return urlparse.unquote(self._db)
        else:
            return self._db

    @db.setter
    def db(self, value):
        if isinstance(value, str):
            self._db = urlparse.quote(value)
        else:
            self._db = value

    @property
    def user(self):
        if isinstance(self._user, str):
            return urlparse.unquote(self._user)
        else:
            return self._user

    @user.setter
    def user(self, value):
        if isinstance(value, str):
            self._user = urlparse.quote(value)
        else:
            self._user = value

    @property
    def branch(self):
        if isinstance(self._branch, str):
            return urlparse.unquote(self._branch)
        else:
            return self._branch

    @branch.setter
    def branch(self, value):
        if isinstance(value, str):
            self._branch = urlparse.quote(value)
        else:
            self._branch = value

    @property
    def repo(self):
        if isinstance(self._repo, str):
            return urlparse.unquote(self._repo)
        else:
            self._repo

    @repo.setter
    def repo(self, value):
        if isinstance(value, str):
            self._repo = urlparse.quote(value)
        else:
            self._repo = value

    @property
    def ref(self):
        return self._ref

    @ref.setter
    def ref(self, value: Optional[str]):
        if value is not None:
            value = value.lower()
        self._ref = value

    def connect(
        self,
        team: str = "admin",
        db: Optional[str] = None,
        remote_auth: Optional[dict] = None,
        use_token: bool = False,
        jwt_token: Optional[str] = None,
        api_token: Optional[str] = None,
        key: str = "root",
        user: str = "admin",
        branch: str = "main",
        ref: Optional[str] = None,
        repo: str = "local",
        **kwargs,
    ) -> None:
        r"""Connect to a Terminus server at the given URI with an API key.

        Stores the connection settings and necessary meta-data for the connected server. You need to connect before most database operations.

        Parameters
        ----------
        team : str
            Name of the team, default to be "admin"
        db : optional, str
            Name of the database connected
        remote_auth : optional, dict
            Remote Auth setting
        key : optional, str
            API key for connecting, default to be "root"
        user : optional, str
            Name of the user, default to be "admin"
        use_token : bool
            Use token to connect. If both `jwt_token` and `api_token` is not provided (None), then it will use the ENV variable TERMINUSDB_ACCESS_TOKEN to connect as the API token
        jwt_token : optional, str
            The Bearer JWT token to connect. Default to be None.
        api_token : optional, strs
            The API token to connect. Default to be None.
        branch : optional, str
            Branch to be connected, default to be "main"
        ref : optional, str
            Ref setting
        repo : optional, str
            Local or remote repo, default to be "local"
        **kwargs
            Extra configuration options.

        Examples
        --------
        >>> client = Client("http://127.0.0.1:6363")
        >>> client.connect(key="root", team="admin", user="admin", db="example_db")
        """

        self.team = team
        self.db = db
        self._remote_auth_dict = remote_auth
        self._key = key
        self.user = user
        if api_token:
            self._use_token = True
        else:
            self._use_token = use_token
        self._jwt_token = jwt_token
        self._api_token = api_token
        self.branch = branch
        self.ref = ref
        self.repo = repo
        self._session = requests.Session()
        self._connected = True

        try:
            self._db_info = self.info()
        except Exception as error:
            raise InterfaceError(
                f"Cannot connect to server, please make sure TerminusDB is running at {self.server_url} and the authentication details are correct. Details: {str(error)}"
            ) from None
        if self.db is not None:
            try:
                _finish_response(
                    self._session.head(
                        self._db_url(),
                        headers=self._default_headers,
                        params={"exists": "true"},
                        auth=self._auth(),
                    )
                )
            except DatabaseError:
                raise InterfaceError(f"Connection fail, {self.db} does not exist.")
        self._author = self.user

    def close(self) -> None:
        """Undo connect and close the connection.

        The connection will be unusable from this point forward; an Error (or subclass) exception will be raised if any operation is attempted with the connection, unless connect is call again."""
        self._connected = False

    def _check_connection(self, check_db=True) -> None:
        """Raise connection InterfaceError if not connected
        Defaults to check if a db is connected"""
        if not self._connected:
            raise InterfaceError("Client is not connected to a TerminusDB server.")
        if check_db and self.db is None:
            raise InterfaceError(
                "No database is connected. Please either connect to a database or create a new database."
            )

    def info(self) -> dict:
        """Get info of a TerminusDB database server

        Returns
        -------
        dict

             Dict with version information:
             ```
             {
               "@type": "api:InfoResponse",
               "api:info": {
                 "authority": "anonymous",
                 "storage": {
                   "version": "1"
                 },
                 "terminusdb": {
                   "git_hash": "53acb38f9aedeec6c524f5679965488788e6ccf5",
                   "version": "10.1.5"
                 },
                 "terminusdb_store": {
                   "version": "0.19.8"
                 }
               },
               "api:status": "api:success"
             }
             ```
        """
        return json.loads(
            _finish_response(
                self._session.get(
                    self.api + "/info",
                    headers=self._default_headers,
                    auth=self._auth(),
                )
            )
        )

    def ok(self) -> bool:
        """Check whether the TerminusDB server is still OK.
           Status is not OK when this function returns false
           or throws an exception (mostly ConnectTimeout)

        Raises
        ------
        Exception
            When a connection can't be made by the requests library

        Returns
        -------
        bool
        """
        if not self._connected:
            return self._connected
        req = self._session.get(
            self.api + "/ok",
            headers=self._default_headers,
            timeout=6
        )
        return req.status_code == 200

    def log(self,
            team: Optional[str] = None,
            db: Optional[str] = None,
            start: int = 0,
            count: int = -1):
        """Get commit history of a database
        Parameters
        ----------
        team : str, optional
             The team from which the database is. Defaults to the class property.
        db : str, optional
             The database. Defaults to the class property.
        start : int, optional
             Commit index to start from. Defaults to 0.
        count : int, optional
             Amount of commits to get. Defaults to -1 which gets all.

        Returns
        -------
        list

             List of the following commit objects:
             ```
               {
                "@id":"InitialCommit/hpl18q42dbnab4vzq8me4bg1xn8p2a0",
                "@type":"InitialCommit",
                "author":"system",
                "identifier":"hpl18q42dbnab4vzq8me4bg1xn8p2a0",
                "message":"create initial schema",
                "schema":"layer_data:Layer_4234adfe377fa9563a17ad764ac37f5dcb14de13668ea725ef0748248229a91b",
                "timestamp":1660919664.9129035
               }
             ```
        """
        self._check_connection(check_db=(not team or not db))
        team = team if team else self.team
        db = db if db else self.db
        result = self._session.get(
            f"{self.api}/log/{team}/{db}",
            params={'start': start, 'count': count},
            headers=self._default_headers,
            auth=self._auth(),
        )
        commits = json.loads(_finish_response(result))
        for commit in commits:
            commit['timestamp'] = datetime.fromtimestamp(commit['timestamp'])
            commit['commit'] = commit['identifier']  # For backwards compat.
        return commits

    def get_commit_history(self, max_history: int = 500) -> list:
        """Get the whole commit history.
        Commit history - Commit id, author of the commit, commit message and the commit time, in the current branch from the current commit, ordered backwards in time, will be returned in a dictionary in the follow format:
        ```
        { "commit_id":
             { "author": "commit_author",
               "message": "commit_message",
               "timestamp: <datetime object of the timestamp>"
             }
        }
        ```

        Parameters
        ----------
        max_history : int, optional
            maximum number of commit that would return, counting backwards from your current commit. Default is set to 500. It needs to be nop-negative, if input is 0 it will still give the last commit.

        Example
        -------
        >>> from terminusdb_client import Client
        >>> client = Client("http://127.0.0.1:6363"
        >>> client.connect(db="bank_balance_example")
        >>> client.get_commit_history()
        [{'commit': 's90wike9v5xibmrb661emxjs8k7ynwc', 'author': 'admin', 'message': 'Adding Jane', 'timestamp': datetime.da
        tetime(2020, 9, 3, 15, 29, 34)}, {'commit': '1qhge8qlodajx93ovj67kvkrkxsw3pg', 'author': 'gavin@terminusdb.com', 'm
        essage': 'Adding Jim', 'timestamp': datetime.datetime(2020, 9, 3, 15, 29, 33)}, {'commit': 'rciy1rfu5foj67ch00ow6f6n
        njjxe3i', 'author': 'gavin@terminusdb.com', 'message': 'Update mike', 'timestamp': datetime.datetime(2020, 9, 3, 15,
         29, 33)}, {'commit': 'n4d86u8juzx852r2ekrega5hl838ovh', 'author': 'gavin@terminusdb.com', 'message': 'Add mike', '
        timestamp': datetime.datetime(2020, 9, 3, 15, 29, 33)}, {'commit': '1vk2i8k8xce26p9jpi4zmq1h5vdqyuj', 'author': 'gav
        in@terminusdb.com', 'message': 'Label for balance was wrong', 'timestamp': datetime.datetime(2020, 9, 3, 15, 29, 33)
        }, {'commit': '9si4na9zv2qol9b189y92fia7ac3hbg', 'author': 'gavin@terminusdb.com', 'message': 'Adding bank account
        object to schema', 'timestamp': datetime.datetime(2020, 9, 3, 15, 29, 33)}, {'commit': '9egc4h0m36l5rbq1alr1fki6jbfu
        kuv', 'author': 'TerminusDB', 'message': 'internal system operation', 'timstamp': datetime.datetime(2020, 9, 3, 15,
         29, 33)}]

        Returns
        -------
        list
        """
        if max_history < 0:
            raise ValueError("max_history needs to be non-negative.")
        return self.log(count=max_history)

    def _get_current_commit(self):
        descriptor = self.db
        if self.branch:
            descriptor = f'{descriptor}/local/branch/{self.branch}'
        commit = self.log(team=self.team, db=descriptor, count=1)[0]
        return commit['identifier']

    def _get_target_commit(self, step):
        descriptor = self.db
        if self.branch:
            descriptor = f'{descriptor}/local/branch/{self.branch}'
        commit = self.log(team=self.team, db=descriptor, count=1, start=step)[0]
        return commit['identifier']

    def get_all_branches(self, get_data_version=False):
        """Get all the branches available in the database."""
        self._check_connection()
        api_url = self._documents_url().split("/")
        api_url = api_url[:-2]
        api_url = "/".join(api_url) + "/_commits"
        result = self._session.get(
            api_url,
            headers=self._default_headers,
            params={"type": "Branch"},
            auth=self._auth(),
        )

        if get_data_version:
            result, version = _finish_response(result, get_data_version)
            return list(_result2stream(result)), version

        return list(_result2stream(_finish_response(result)))

    def rollback(self, steps=1) -> None:
        """Curently not implementated. Please check back later.

        Raises
        ----------
        NotImplementedError
            Since TerminusDB currently does not support open transactions. This method is not applicable to it's usage. To reset commit head, use Client.reset

        """
        raise NotImplementedError(
            "Open transactions are currently not supported. To reset commit head, check Client.reset"
        )

    def copy(self) -> "Client":
        """Create a deep copy of this client.

        Returns
        -------
        Client
            The copied client instance.

        Examples
        --------
        >>> client = Client("http://127.0.0.1:6363/")
        >>> clone = client.copy()
        >>> assert client is not clone
        """
        return copy.deepcopy(self)

    def set_db(self, dbid: str, team: Optional[str] = None) -> str:
        """Set the connection to another database. This will reset the connection.

        Parameters
        ----------
        dbid : str
            Database identifer to set in the config.
        team : str
            Team identifer to set in the config. If not passed in, it will use the current one.

        Returns
        -------
        str
            The current database identifier.

        Examples
        --------
        >>> client = Client("http://127.0.0.1:6363")
        >>> client.set_db("database1")
        'database1'
        """
        self._check_connection(check_db=False)

        if team is None:
            team = self.team

        return self.connect(
            team=team,
            db=dbid,
            remote_auth=self._remote_auth_dict,
            key=self._key,
            user=self.user,
            branch=self.branch,
            ref=self.ref,
            repo=self.repo,
        )

    def _get_prefixes(self):
        """Get the prefixes for a given database"""
        self._check_connection()
        result = self._session.get(
            self._db_base("prefixes"),
            headers=self._default_headers,
            auth=self._auth(),
        )
        return json.loads(_finish_response(result))

    def create_database(
        self,
        dbid: str,
        team: Optional[str] = None,
        label: Optional[str] = None,
        description: Optional[str] = None,
        prefixes: Optional[dict] = None,
        include_schema: bool = True,
    ) -> None:
        """Create a TerminusDB database by posting
        a terminus:Database document to the Terminus Server.

        Parameters
        ----------
        dbid : str
            Unique identifier of the database.
        team : str, optional
            ID of the Team in which to create the DB (defaults to 'admin')
        label : str, optional
            Database name.
        description : str, optional
            Database description.
        prefixes : dict, optional
            Optional dict containing ``"@base"`` and ``"@schema"`` keys.

            @base (str)
                IRI to use when ``doc:`` prefixes are expanded. Defaults to ``terminusdb:///data``.
            @schema (str)
                IRI to use when ``scm:`` prefixes are expanded. Defaults to ``terminusdb:///schema``.
        include_schema : bool
            If ``True``, a main schema graph will be created, otherwise only a main instance graph will be created.

        Raises
        ------
        InterfaceError
            if the client does not connect to a server

        Examples
        --------
        >>> client = Client("http://127.0.0.1:6363/")
        >>> client.create_database("someDB", "admin", "Database Label", "My Description")
        """

        self._check_connection(check_db=False)

        details: Dict[str, Any] = {}
        if label:
            details["label"] = label
        else:
            details["label"] = dbid
        if description:
            details["comment"] = description
        else:
            details["comment"] = ""
        if include_schema:
            details["schema"] = True
        else:
            details["schema"] = False
        if prefixes:
            details["prefixes"] = prefixes
        if team is None:
            team = self.team

        self.team = team
        self._connected = True
        self.db = dbid

        _finish_response(
            self._session.post(
                self._db_url(),
                headers=self._default_headers,
                json=details,
                auth=self._auth(),
            )
        )

    def delete_database(
        self,
        dbid: Optional[str] = None,
        team: Optional[str] = None,
        force: bool = False,
    ) -> None:
        """Delete a TerminusDB database.

        If ``team`` is provided, then the team in the config will be updated
        and the new value will be used in future requests to the server.

        Parameters
        ----------
        dbid : str
            ID of the database to delete
        team : str, optional
            the team in which the database resides (defaults to "admin")
        force : bool

        Raises
        ------
        UserWarning
            If the value of dbid is None.
        InterfaceError
            if the client does not connect to a server.

        Examples
        --------
        >>> client = Client("http://127.0.0.1:6363/")
        >>> client.delete_database("<database>", "<team>")
        """

        self._check_connection(check_db=False)

        if dbid is None:
            raise UserWarning(
                f"You are currently using the database: {self.team}/{self.db}. If you want to delete it, please do 'delete_database({self.db},{self.team})' instead."
            )

        self.db = dbid
        if team is None:
            warnings.warn(
                f"Delete Database Warning: You have not specify the team, assuming {self.team}/{self.db}",
                stacklevel=2,
            )
        else:
            self.team = team
        payload = {}
        if force:
            payload["force"] = "true"
        _finish_response(
            self._session.delete(
                self._db_url(),
                headers=self._default_headers,
                auth=self._auth(),
                params=payload,
            )
        )
        self.db = None

    def get_triples(self, graph_type: GraphType) -> str:
        """Retrieves the contents of the specified graph as triples encoded in turtle format

        Parameters
        ----------
        graph_type : GraphType
            Graph type, either GraphType.INSTANCE or GraphType.SCHEMA.

        Raises
        ------
        InterfaceError
            if the client does not connect to a database

        Returns
        -------
        str
        """
        self._check_connection()
        result = self._session.get(
            self._triples_url(graph_type),
            headers=self._default_headers,
            auth=self._auth(),
        )
        return json.loads(_finish_response(result))

    def update_triples(self, graph_type: GraphType, content: str, commit_msg: str) -> None:
        """Updates the contents of the specified graph with the triples encoded in turtle format.
           Replaces the entire graph contents

        Parameters
        ----------
        graph_type : GraphType
            Graph type, either GraphType.INSTANCE or GraphType.SCHEMA.
        content
            Valid set of triples in Turtle or Trig format.
        commit_msg : str
            Commit message.

        Raises
        ------
        InterfaceError
            if the client does not connect to a database
        """
        self._check_connection()
        params = {"commit_info": self._generate_commit(commit_msg),
                  "turtle": content,
                  }
        result = self._session.post(
            self._triples_url(graph_type),
            headers=self._default_headers,
            json=params,
            auth=self._auth(),
        )
        return json.loads(_finish_response(result))

    def insert_triples(
        self, graph_type: GraphType, content: str, commit_msg: Optional[str] = None
    ) -> None:
        """Inserts into the specified graph with the triples encoded in turtle format.

        Parameters
        ----------
        graph_type : GraphType
            Graph type, either GraphType.INSTANCE or GraphType.SCHEMA.
        content
            Valid set of triples in Turtle or Trig format.
        commit_msg : str
            Commit message.

        Raises
        ------
        InterfaceError
            if the client does not connect to a database
        """
        self._check_connection()
        params = {"commit_info": self._generate_commit(commit_msg),
                  "turtle": content
                  }
        result = self._session.put(
            self._triples_url(graph_type),
            headers=self._default_headers,
            json=params,
            auth=self._auth(),
        )
        return json.loads(_finish_response(result))

    def query_document(
        self,
        document_template: dict,
        graph_type: GraphType = GraphType.INSTANCE,
        skip: int = 0,
        count: Optional[int] = None,
        as_list: bool = False,
        get_data_version: bool = False,
        **kwargs,
    ) -> Union[Iterable, list]:
        """Retrieves all documents that match a given document template

        Parameters
        ----------
        document_template : dict
            Template for the document that is being retrived
        graph_type : GraphType
            Graph type, either GraphType.INSTANCE or GraphType.SCHEMA.
        as_list : bool
            If the result returned as list rather than an iterator.
        get_data_version : bool
            If the data version of the document(s) should be obtained. If True, the method return the result and the version as a tuple.

        Raises
        ------
        InterfaceError
            if the client does not connect to a database

        Returns
        -------
        Iterable
        """
        self._check_connection()

        payload = {"query": document_template, "graph_type": graph_type}
        payload["skip"] = skip
        if count is not None:
            payload["count"] = count
        add_args = ["prefixed", "minimized", "unfold"]
        for the_arg in add_args:
            if the_arg in kwargs:
                payload[the_arg] = kwargs[the_arg]
        headers = self._default_headers.copy()
        headers["X-HTTP-Method-Override"] = "GET"
        result = self._session.post(
            self._documents_url(),
            headers=headers,
            json=payload,
            auth=self._auth(),
        )
        if get_data_version:
            result, version = _finish_response(result, get_data_version)
            return_obj = _result2stream(result)
            if as_list:
                return list(return_obj), version
            else:
                return return_obj, version

        return_obj = _result2stream(_finish_response(result))
        if as_list:
            return list(return_obj)
        else:
            return return_obj

    def get_document(
        self,
        iri_id: str,
        graph_type: GraphType = GraphType.INSTANCE,
        get_data_version: bool = False,
        **kwargs,
    ) -> dict:
        """Retrieves the document of the iri_id

        Parameters
        ----------
        iri_id : str
            Iri id for the document that is to be retrieved
        graph_type : GraphType
            Graph type, either GraphType.INSTANCE or GraphType.SCHEMA.
        get_data_version : bool
            If the data version of the document(s) should be obtained. If True, the method return the result and the version as a tuple.
        kwargs :
            Additional boolean flags for retriving. Currently avaliable: "prefixed", "minimized", "unfold"

        Raises
        ------
        InterfaceError
            if the client does not connect to a database

        Returns
        -------
        dict
        """
        add_args = ["prefixed", "minimized", "unfold"]
        self._check_connection()
        payload = {"id": iri_id, "graph_type": graph_type}
        for the_arg in add_args:
            if the_arg in kwargs:
                payload[the_arg] = kwargs[the_arg]

        result = self._session.get(
            self._documents_url(),
            headers=self._default_headers,
            params=payload,
            auth=self._auth(),
        )

        if get_data_version:
            result, version = _finish_response(result, get_data_version)
            return json.loads(result), version

        return json.loads(_finish_response(result))

    def get_documents_by_type(
        self,
        doc_type: str,
        graph_type: GraphType = GraphType.INSTANCE,
        skip: int = 0,
        count: Optional[int] = None,
        as_list: bool = False,
        get_data_version=False,
        **kwargs,
    ) -> Union[Iterable, list]:
        """Retrieves the documents by type

        Parameters
        ----------
        doc_type : str
            Specific type for the docuemnts that is retriving
        graph_type : GraphType, optional
            Graph type, either GraphType.INSTANCE or GraphType.SCHEMA.
        skip : int
            The starting posiion of the returning results, default to be 0
        count : int or None
            The maximum number of returned result, if None (default) it will return all of the avalible result.
        as_list : bool
            If the result returned as list rather than an iterator.
        get_data_version : bool
            If the version of the document(s) should be obtained. If True, the method return the result and the version as a tuple.
        kwargs :
            Additional boolean flags for retriving. Currently avaliable: "prefixed", "unfold"

        Raises
        ------
        InterfaceError
            if the client does not connect to a database

        Returns
        -------
        iterable
            Stream of dictionaries
        """
        return self.get_all_documents(graph_type, skip, count,
                                      as_list, get_data_version,
                                      doc_type=doc_type, **kwargs)

    def get_all_documents(
        self,
        graph_type: GraphType = GraphType.INSTANCE,
        skip: int = 0,
        count: Optional[int] = None,
        as_list: bool = False,
        get_data_version: bool = False,
        doc_type: Optional[str] = None,
        **kwargs,
    ) -> Union[Iterable, list, tuple]:
        """Retrieves all avalibale the documents

        Parameters
        ----------
        graph_type : GraphType, optional
            Graph type, either GraphType.INSTANCE or GraphType.SCHEMA.
        skip : int
            The starting posiion of the returning results, default to be 0
        count : int or None
            The maximum number of returned result, if None (default) it will return all of the avalible result.
        as_list : bool
            If the result returned as list rather than an iterator.
        get_data_version : bool
            If the version of the document(s) should be obtained. If True, the method return the result and the version as a tuple.
        kwargs :
            Additional boolean flags for retriving. Currently avaliable: "prefixed", "unfold"

        Raises
        ------
        InterfaceError
            if the client does not connect to a database

        Returns
        -------
        iterable
            Stream of dictionaries
        """
        add_args = ["prefixed", "unfold"]
        self._check_connection()
        payload = _args_as_payload({"graph_type": graph_type,
                                    "skip": skip,
                                    "type": doc_type,
                                    "count": count,
                                    })
        for the_arg in add_args:
            if the_arg in kwargs:
                payload[the_arg] = kwargs[the_arg]
        result = self._session.get(
            self._documents_url(),
            headers=self._default_headers,
            params=payload,
            auth=self._auth(),
        )

        if get_data_version:
            result, version = _finish_response(result, get_data_version)
            return_obj = _result2stream(result)
            if as_list:
                return list(return_obj), version
            else:
                return return_obj, version

        return_obj = _result2stream(_finish_response(result))
        if as_list:
            return list(return_obj)
        else:
            return return_obj

    def get_existing_classes(self):
        """Get all the existing classes (only ids) in a database."""
        all_existing_obj = self.get_all_documents(graph_type="schema")
        all_existing_class = {}
        for item in all_existing_obj:
            if item.get("@id"):
                all_existing_class[item["@id"]] = item
        return all_existing_class

    def _conv_to_dict(self, obj):
        if isinstance(obj, dict):
            return _clean_dict(obj)
        elif hasattr(obj, "to_dict"):
            return obj.to_dict()
        elif hasattr(obj, "_to_dict"):
            if hasattr(obj, "_isinstance") and obj._isinstance:
                if hasattr(obj.__class__, "_subdocument"):
                    raise ValueError("Subdocument cannot be added directly")
                (d, refs) = obj._obj_to_dict()
                # merge all refs
                self._references = {**self._references, **refs}
                return d
            else:
                return obj._to_dict()
        else:
            raise ValueError("Object cannot convert to dictionary")

    def _unseen(self, seen):
        unseen = []
        for key in self._references:
            if key not in seen:
                unseen.append(self._references[key])
        return unseen

    def _convert_document(self, document, graph_type):
        if not isinstance(document, list):
            document = [document]

        seen = {}
        objects = []
        while document != []:
            for item in document:
                if hasattr(item, "to_dict") and graph_type != "schema":
                    raise InterfaceError(
                        "Inserting Schema object into non-schema graph."
                    )
                item_dict = self._conv_to_dict(item)
                if hasattr(item, "_capture"):
                    seen[item._capture] = item_dict
                else:
                    if isinstance(item_dict, list):
                        objects += item_dict
                    else:
                        objects.append(item_dict)

            document = self._unseen(seen)

        return list(seen.values()) + objects

    def insert_document(
        self,
        document: Union[
            dict,
            List[dict],
            "Schema",  # noqa:F821
            "DocumentTemplate",  # noqa:F821
            List["DocumentTemplate"],  # noqa:F821
        ],
        graph_type: GraphType = GraphType.INSTANCE,
        full_replace: bool = False,
        commit_msg: Optional[str] = None,
        last_data_version: Optional[str] = None,
        compress: Union[str, int] = 1024,
        raw_json: bool = False
    ) -> None:
        """Inserts the specified document(s)

        Parameters
        ----------
        document : dict or list of dict
            Document(s) to be inserted.
        graph_type : GraphType
            Graph type, either GraphType.INSTANCE or GraphType.SCHEMA.
        full_replace : bool
            If True then the whole graph will be replaced. WARNING: you should also supply the context object as the first element in the list of documents  if using this option.
        commit_msg : str
            Commit message.
        last_data_version : str
            Last version before the update, used to check if the document has been changed unknowingly
        compress : str or int
            If it is an integer, size of the data larger than this (in bytes) will be compress with gzip in the request (assume encoding as UTF-8, 0 = always compress). If it is `never` it will never compress the data.
        raw_json : bool
            Update as raw json

        Raises
        ------
        InterfaceError
            if the client does not connect to a database

        Returns
        -------
        list
            list of ids of the inseted docuemnts
        """
        self._check_connection()
        params = self._generate_commit(commit_msg)
        params["graph_type"] = graph_type
        if full_replace:
            params["full_replace"] = "true"
        else:
            params["full_replace"] = "false"
        params["raw_json"] = "true" if raw_json else "false"

        headers = self._default_headers.copy()
        if last_data_version is not None:
            headers["TerminusDB-Data-Version"] = last_data_version

        # make sure we track only internal references
        self._references = {}
        new_doc = self._convert_document(document, graph_type)
        all_docs = list(self._references.values())
        self._references = {}

        if len(new_doc) == 0:
            return

        if full_replace:
            if new_doc[0].get("@type") != "@context":
                raise ValueError(
                    "The first item in docuemnt need to be dictionary representing the context object."
                )
        else:
            if new_doc[0].get("@type") == "@context":
                warnings.warn(
                    "To replace context, need to use `full_replace` or `replace_document`, skipping context object now.",
                    stacklevel=2,
                )
                new_doc.pop(0)

        json_string = json.dumps(new_doc).encode("utf-8")
        if compress != "never" and len(json_string) > compress:
            headers.update(
                {"Content-Encoding": "gzip", "Content-Type": "application/json"}
            )
            result = self._session.post(
                self._documents_url(),
                headers=headers,
                params=params,
                data=gzip.compress(json_string),
                auth=self._auth(),
            )
        else:
            result = self._session.post(
                self._documents_url(),
                headers=headers,
                params=params,
                json=new_doc,
                auth=self._auth(),
            )
        result = json.loads(_finish_response(result))
        if isinstance(all_docs, list):
            for idx, item in enumerate(all_docs):
                if hasattr(item, "_obj_to_dict") and not hasattr(item, "_backend_id"):
                    item._backend_id = result[idx]
        return result

    def replace_document(
        self,
        document: Union[
            dict,
            List[dict],
            "Schema",  # noqa:F821
            "DocumentTemplate",  # noqa:F821
            List["DocumentTemplate"],  # noqa:F821
        ],
        graph_type: GraphType = GraphType.INSTANCE,
        commit_msg: Optional[str] = None,
        last_data_version: Optional[str] = None,
        compress: Union[str, int] = 1024,
        create: bool = False,
        raw_json: bool = False,
    ) -> dict:
        """Updates the specified document(s)

        Parameters
        ----------
        document : dict or list of dict
            Document(s) to be updated.
        graph_type : GraphType
            Graph type, either GraphType.INSTANCE or GraphType.SCHEMA.
        commit_msg : str
            Commit message.
        last_data_version : str
            Last version before the update, used to check if the document has been changed unknowingly
        compress : str or int
            If it is an integer, size of the data larger than this (in bytes) will be compress with gzip in the request (assume encoding as UTF-8, 0 = always compress). If it is `never` it will never compress the data.
        create : bool
            Create the document if it does not yet exist.
        raw_json : bool
            Update as raw json

        Raises
        ------
        InterfaceError
            if the client does not connect to a database
        """
        self._check_connection()
        params = self._generate_commit(commit_msg)
        params["graph_type"] = graph_type
        params["create"] = "true" if create else "false"
        params["raw_json"] = "true" if raw_json else "false"

        headers = self._default_headers.copy()
        if last_data_version is not None:
            headers["TerminusDB-Data-Version"] = last_data_version

        self._references = {}
        new_doc = self._convert_document(document, graph_type)
        all_docs = list(self._references.values())
        self._references = {}

        json_string = json.dumps(new_doc).encode("utf-8")
        if compress != "never" and len(json_string) > compress:
            headers.update(
                {"Content-Encoding": "gzip", "Content-Type": "application/json"}
            )
            result = self._session.put(
                self._documents_url(),
                headers=headers,
                params=params,
                data=gzip.compress(json_string),
                auth=self._auth(),
            )
        else:
            result = self._session.put(
                self._documents_url(),
                headers=headers,
                params=params,
                json=new_doc,
                auth=self._auth(),
            )
        result = json.loads(_finish_response(result))
        if isinstance(all_docs, list):
            for idx, item in enumerate(all_docs):
                if hasattr(item, "_obj_to_dict") and not hasattr(item, "_backend_id"):
                    item._backend_id = result[idx][len("terminusdb:///data/") :]
        return result

    def update_document(
        self,
        document: Union[
            dict,
            List[dict],
            "Schema",  # noqa:F821
            "DocumentTemplate",  # noqa:F821
            List["DocumentTemplate"],  # noqa:F821
        ],
        graph_type: GraphType = GraphType.INSTANCE,
        commit_msg: Optional[str] = None,
        last_data_version: Optional[str] = None,
        compress: Union[str, int] = 1024,
    ) -> None:
        """Updates the specified document(s). Add the document if not existed.

        Parameters
        ----------
        document : dict or list of dict
            Document(s) to be updated.
        graph_type : GraphType
            Graph type, either GraphType.INSTANCE or GraphType.SCHEMA.
        commit_msg : str
            Commit message.
        last_data_version : str
            Last version before the update, used to check if the document has been changed unknowingly
        compress : str or int
            If it is an integer, size of the data larger than this (in bytes) will be compress with gzip in the request (assume encoding as UTF-8, 0 = always compress). If it is `never` it will never compress the data.

        Raises
        ------
        InterfaceError
            if the client does not connect to a database
        """
        self.replace_document(
            document, graph_type, commit_msg, last_data_version, compress, True
        )

    def delete_document(
        self,
        document: Union[str, list, dict, Iterable],
        graph_type: GraphType = GraphType.INSTANCE,
        commit_msg: Optional[str] = None,
        last_data_version: Optional[str] = None,
    ) -> None:
        """Delete the specified document(s)

        Parameters
        ----------
        document : str or list of str
            Document(s) (as dictionary or DocumentTemplate objects) or id(s) of document(s) to be updated.
        graph_type : GraphType
            Graph type, either GraphType.INSTANCE or GraphType.SCHEMA.
        commit_msg : str
            Commit message.
        last_data_version : str
            Last version before the update, used to check if the document has been changed unknowingly

        Raises
        ------
        InterfaceError
            if the client does not connect to a database
        """
        self._check_connection()
        doc_id = []
        if not isinstance(document, (str, list, dict)) and hasattr(
            document, "__iter__"
        ):
            document = list(document)
        if not isinstance(document, list):
            document = [document]
        for doc in document:
            if hasattr(doc, "_obj_to_dict"):
                (doc, refs) = doc._obj_to_dict()
            if isinstance(doc, dict) and doc.get("@id"):
                doc_id.append(doc.get("@id"))
            elif isinstance(doc, str):
                doc_id.append(doc)
        params = self._generate_commit(commit_msg)
        params["graph_type"] = graph_type

        headers = self._default_headers.copy()
        if last_data_version is not None:
            headers["TerminusDB-Data-Version"] = last_data_version

        _finish_response(
            self._session.delete(
                self._documents_url(),
                headers=headers,
                params=params,
                json=doc_id,
                auth=self._auth(),
            )
        )

    def has_doc(self, doc_id: str, graph_type: GraphType = GraphType.INSTANCE) -> bool:
        """Check if a certain document exist in a database

        Parameters
        ----------
        doc_id : str
            Id of document to be checked.
        graph_type : GraphType
            Graph type, either GraphType.INSTANCE or GraphType.SCHEMA.

        Raises
        ------
        InterfaceError
            if the client does not connect to a database

        Returns
        -------
        Bool
            if the document exist
        """
        self._check_connection()

        response = self._session.get(
            self._documents_url(),
            headers=self._default_headers,
            json={"id": doc_id, "graph_type": graph_type},
            auth=self._auth(),
        )
        try:
            _finish_response(response)
            return True
        except DatabaseError as exception:
            body = exception.error_obj
            if exception.status_code == 404 and "api:error" in body and body["api:error"]["@type"] == "api:DocumentNotFound":
                return False
            raise exception

    def get_class_frame(self, class_name):
        """Get the frame of the class of class_name. Provide information about all the avaliable properties of that class.

        Parameters
        ----------
        class_name : str
            Name of the class

        Returns
        -------
        dict
            Dictionary containing information
        """
        self._check_connection()
        opts = {"type": class_name}
        result = self._session.get(
            self._class_frame_url(),
            headers=self._default_headers,
            params=opts,
            auth=self._auth(),
        )
        return json.loads(_finish_response(result))

    def commit(self):
        """Not implementated: open transactions currently not suportted. Please check back later."""

    def query(
        self,
        woql_query: Union[dict, WOQLQuery],
        commit_msg: Optional[str] = None,
        get_data_version: bool = False,
        last_data_version: Optional[str] = None,
        streaming: bool = False,
        # file_dict: Optional[dict] = None,
    ) -> Union[dict, str, WoqlResult]:
        """Updates the contents of the specified graph with the triples encoded in turtle format Replaces the entire graph contents

        Parameters
        ----------
        woql_query : dict or WOQLQuery object
            A woql query as an object or dict
        commit_mg : str
            A message that will be written to the commit log to describe the change
        get_data_version : bool
            If the data version of the query result(s) should be obtained. If True, the method return the result and the version as a tuple.
        last_data_version : str
            Last version before the update, used to check if the document has been changed unknowingly
        file_dict : **deprecated**
            File dictionary to be associated with post name => filename, for multipart POST

        Raises
        ------
        InterfaceError
            if the client does not connect to a database

        Examples
        --------
        >>> Client(server="http://localhost:6363").query(woql, "updating graph")

        Returns
        -------
        dict
        """
        self._check_connection()
        query_obj = {"commit_info": self._generate_commit(commit_msg)}
        if isinstance(woql_query, WOQLQuery):
            request_woql_query = woql_query.to_dict()
        else:
            request_woql_query = woql_query
        query_obj["query"] = request_woql_query
        query_obj["streaming"] = streaming

        headers = self._default_headers.copy()
        if last_data_version is not None:
            headers["TerminusDB-Data-Version"] = last_data_version

        result = self._session.post(
            self._query_url(),
            headers=headers,
            json=query_obj,
            auth=self._auth(),
            stream=streaming
        )

        if streaming:
            return WoqlResult(lines=_finish_response(result, streaming=True))

        if get_data_version:
            result, version = _finish_response(result, get_data_version)
            result = json.loads(result)
        else:
            result = json.loads(_finish_response(result))

        if result.get("inserts") or result.get("deletes"):
            return "Commit successfully made."
        elif get_data_version:
            return result, version
        else:
            return result

    def create_branch(self, new_branch_id: str, empty: bool = False) -> None:
        """Create a branch starting from the current branch.

        Parameters
        ----------
        new_branch_id : str
            New branch identifier.
        empty : bool
            Create an empty branch if true (no starting commit)

        Raises
        ------
        InterfaceError
            if the client does not connect to a database
        """
        self._check_connection()
        if empty:
            source = {}
        elif self.ref:
            source = {"origin": f"{self.team}/{self.db}/{self.repo}/commit/{self.ref}"}
        else:
            source = {
                "origin": f"{self.team}/{self.db}/{self.repo}/branch/{self.branch}"
            }

        _finish_response(
            self._session.post(
                self._branch_url(new_branch_id),
                headers=self._default_headers,
                json=source,
                auth=self._auth(),
            )
        )

    def delete_branch(self, branch_id: str) -> None:
        """Delete a branch

        Parameters
        ----------
        branch_id : str
            Branch to delete

        Raises
        ------
        InterfaceError
            if the client does not connect to a database
        """
        self._check_connection()

        _finish_response(
            self._session.delete(
                self._branch_url(branch_id),
                headers=self._default_headers,
                auth=self._auth(),
            )
        )

    def pull(
        self,
        remote: str = "origin",
        remote_branch: Optional[str] = None,
        message: Optional[str] = None,
        author: Optional[str] = None,
    ) -> dict:
        """Pull updates from a remote repository to the current database.

        Parameters
        ----------
        remote : str
            remote to pull from, default "origin"
        remote_branch : str, optional
            remote branch to pull from, default to be your current barnch
        message : str, optional
            optional commit message
        author : str, optional
            option to overide the author of the operation

        Raises
        ------
        InterfaceError
            if the client does not connect to a database

        Returns
        -------
        dict

        Examples
        --------
        >>> client = Client("http://127.0.0.1:6363/")
        >>> client.pull()
        """
        self._check_connection()
        if remote_branch is None:
            remote_branch = self.branch
        if author is None:
            author = self.author
        if message is None:
            message = (
                f"Pulling from {remote}/{remote_branch} by Python client {__version__}"
            )
        rc_args = {
            "remote": remote,
            "remote_branch": remote_branch,
            "author": author,
            "message": message,
        }

        result = self._session.post(
            self._pull_url(),
            headers=self._default_headers,
            json=rc_args,
            auth=self._auth(),
        )

        return json.loads(_finish_response(result))

    def fetch(self, remote_id: str,
              remote_auth: Optional[dict] = None,
              ) -> dict:
        """Fetch the branch from a remote repo

        Parameters
        ----------
        remote_id : str
            id of the remote

        Raises
        ------
        InterfaceError
            if the client does not connect to a database"""
        self._check_connection()

        result = self._session.post(
            self._fetch_url(remote_id),
            headers=self._default_headers,
            auth=self._auth(),
        )

        return json.loads(_finish_response(result))

    def push(
        self,
        remote: str = "origin",
        remote_branch: Optional[str] = None,
        message: Optional[str] = None,
        author: Optional[str] = None,
        remote_auth: Optional[dict] = None,
    ) -> dict:
        """Push changes from a branch to a remote repo

        Parameters
        ----------
        remote : str
            remote to push to, default "origin"
        remote_branch : str, optional
            remote branch to push to, default to be your current barnch
        message : str, optional
            optional commit message
        author : str, optional
            option to overide the author of the operation
        remote_auth : dict, optional
            optional remote authorization (uses client remote auth otherwise)

        Raises
        ------
        InterfaceError
            if the client does not connect to a database

        Examples
        --------
        >>> Client(server="http://localhost:6363").push(remote="origin", remote_branch = "main", author = "admin", message = "commit message"})

        Returns
        -------
        dict
        """
        self._check_connection()
        if remote_branch is None:
            remote_branch = self.branch
        if author is None:
            author = self._author
        if message is None:
            message = (
                f"Pushing to {remote}/{remote_branch} by Python client {__version__}"
            )
        rc_args = {
            "remote": remote,
            "remote_branch": remote_branch,
            "author": author,
            "message": message,
        }
        if self._remote_auth_dict or remote_auth:
            headers = {'Authorization-Remote' : self._generate_remote_header(remote_auth) if remote_auth else self._remote_auth()}
        headers.update(self._default_headers)

        result = self._session.post(
            self._push_url(),
            headers=headers,
            json=rc_args,
            auth=self._auth(),
        )

        return json.loads(_finish_response(result))

    def rebase(
        self,
        branch: Optional[str] = None,
        commit: Optional[str] = None,
        rebase_source: Optional[str] = None,
        message: Optional[str] = None,
        author: Optional[str] = None,
    ) -> dict:
        """Rebase the current branch onto the specified remote branch. Need to specify one of 'branch','commit' or the 'rebase_source'.

        Notes
        -----
        The "remote" repo can live in the local database.

        Parameters
        ----------
        branch : str, optional
            the branch for the rebase
        rebase_source : str, optional
            the source branch for the rebase
        message : str, optional
            the commit message
        author : str, optional
            the commit author

        Raises
        ------
        InterfaceError
            if the client does not connect to a database

        Returns
        -------
        dict

        Examples
        --------
        >>> client = Client("http://127.0.0.1:6363/")
        >>> client.rebase("the_branch")
        """
        self._check_connection()

        if branch is not None and commit is None:
            rebase_source = "/".join([self.team, self.db, self.repo, "branch", branch])
        elif branch is None and commit is not None:
            rebase_source = "/".join([self.team, self.db, self.repo, "commit", commit])
        elif branch is not None or commit is not None:
            raise RuntimeError("Cannot specify both branch and commit.")
        elif rebase_source is None:
            raise RuntimeError(
                "Need to specify one of 'branch', 'commit' or the 'rebase_source'"
            )

        if author is None:
            author = self._author
        if message is None:
            message = f"Rebase from {rebase_source} by Python client {__version__}"
        rc_args = {"rebase_from": rebase_source, "author": author, "message": message}

        result = self._session.post(
            self._rebase_url(),
            headers=self._default_headers,
            json=rc_args,
            auth=self._auth(),
        )

        return json.loads(_finish_response(result))

    def reset(
        self, commit: Optional[str] = None, soft: bool = False, use_path: bool = False
    ) -> None:
        """Reset the current branch HEAD to the specified commit path. If `soft` is not True, it will be a hard reset, meaning reset to that commit in the backend and newer commit will be wipped out. If `soft` is True, the client will only reference to that commit and can be reset to the newest commit when done.

        Raises
        ------
        InterfaceError
            if the client does not connect to a database

        Notes
        -----
        The "remote" repo can live in the local database.

        Parameters
        ----------
        commit : string
            Commit id or path to the commit (if use_path is True), for instance '234980523ffaf93' or 'admin/database/local/commit/234980523ffaf93'. If not provided, it will reset to the newest commit (useful when need to go back after a soft reset).
        soft : bool
            Flag indicating if the reset if soft, that is referencing to a previous commit instead of resetting to a previous commit in the backend and wipping newer commits.
        use_path : bool
            Wheather or not the commit given is an id or path. Default using id and use_path is False.

        Examples
        --------
        >>> client = Client("http://127.0.0.1:6363/")
        >>> client.reset('234980523ffaf93')
        >>> client.reset('admin/database/local/commit/234980523ffaf93', use_path=True)
        """

        self._check_connection()
        if soft:
            if use_path:
                self._ref = commit.split("/")[-1]
            else:
                self._ref = commit
            return None
        else:
            self._ref = None

        if commit is None:
            return None

        if use_path:
            commit_path = commit
        else:
            commit_path = f"{self.team}/{self.db}/{self.repo}/commit/{commit}"

        _finish_response(
            self._session.post(
                self._reset_url(),
                headers=self._default_headers,
                json={"commit_descriptor": commit_path},
                auth=self._auth(),
            )
        )

    def optimize(self, path: str) -> None:
        """Optimize the specified path.

        Raises
        ------
        InterfaceError
            if the client does not connect to a database

        Notes
        -----
        The "remote" repo can live in the local database.

        Parameters
        ----------
        path : string
            Path to optimize, for instance admin/database/_meta for the repo graph.

        Examples
        --------
        >>> client = Client("http://127.0.0.1:6363/")
        >>> client.optimize('admin/database') # optimise database branch (here main)
        >>> client.optimize('admin/database/_meta') # optimise the repository graph (actually creates a squashed flat layer)
        >>> client.optimize('admin/database/local/_commits') # commit graph is optimised
        """
        self._check_connection()

        _finish_response(
            self._session.post(
                self._optimize_url(path),
                headers=self._default_headers,
                auth=self._auth(),
            )
        )

    def squash(
        self,
        message: Optional[str] = None,
        author: Optional[str] = None,
        reset: bool = False,
    ) -> str:
        """Squash the current branch HEAD into a commit

        Raises
        ------
        InterfaceError
            if the client does not connect to a database

        Notes
        -----
        The "remote" repo can live in the local database.

        Parameters
        ----------
        message : string
            Message for the newly created squash commit
        author : string
            Author of the commit
        reset : bool
            Perform reset after squash

        Returns
        -------
        str
            commit id to be reset

        Examples
        --------
        >>> client = Client("http://127.0.0.1:6363/")
        >>> client.connect(user="admin", key="root", team="admin", db="some_db")
        >>> client.squash('This is a squash commit message!')
        """
        self._check_connection()

        result = self._session.post(
            self._squash_url(),
            headers=self._default_headers,
            json={"commit_info": self._generate_commit(message, author)},
            auth=self._auth(),
        )

        # API response:
        # {'@type' : 'api:SquashResponse',
        # 'api:commit' : Commit,
        # 'api:old_commit' : Old_Commit,
        # 'api:status' : "api:success"}

        commit_id = json.loads(_finish_response(result)).get("api:commit")
        if reset:
            self.reset(commit_id)
        return commit_id

    def _convert_diff_document(self, document):
        if isinstance(document, list):
            new_doc = []
            for item in document:
                item_dict = self._conv_to_dict(item)
                new_doc.append(item_dict)
        else:
            new_doc = self._conv_to_dict(document)
        return new_doc

    def apply(self,
              before_version,
              after_version,
              branch=None,
              message=None,
              author=None):
        """Diff two different commits and apply changes on branch

        Parameters
        ----------
        before_version : string
            Before branch/commit to compare
        after_object : string
            After branch/commit to compare
        branch : string
            Branch to apply to. Optional.
        """
        self._check_connection()
        branch = branch if branch else self.branch
        return json.loads(
            _finish_response(
                self._session.post(
                    self._apply_url(branch=branch),
                    headers=self._default_headers,
                    json={
                        "commit_info": self._generate_commit(message, author),
                        "before_commit": before_version,
                        "after_commit": after_version,
                    },
                    auth=self._auth(),
                )
            )
        )

    def diff_object(self, before_object, after_object):
        """Diff two different objects.

        Parameters
        ----------
        before_object : string
            Before object to compare
        after_object : string
            After object to compare
        """
        self._check_connection(check_db=False)
        return json.loads(
            _finish_response(
                self._session.post(
                    self._diff_url(),
                    headers=self._default_headers,
                    json={'before': before_object,
                          'after': after_object},
                    auth=self._auth(),
                )
            )
        )

    def diff_version(self, before_version, after_version):
        """Diff two different versions. Can either be a branch or a commit

        Parameters
        ----------
        before_version : string
            Commit or branch of the before version to compare
        after_version : string
            Commit or branch of the after version to compare
        """
        self._check_connection(check_db=False)
        return json.loads(
            _finish_response(
                self._session.post(
                    self._diff_url(),
                    headers=self._default_headers,
                    json={'before_data_version': before_version,
                          'after_data_version': after_version},
                    auth=self._auth(),
                )
            )
        )

    def diff(
        self,
        before: Union[
            str,
            dict,
            List[dict],
            "Schema",  # noqa:F821
            "DocumentTemplate",  # noqa:F821
            List["DocumentTemplate"],  # noqa:F821
        ],
        after: Union[
            str,
            dict,
            List[dict],
            "Schema",  # noqa:F821
            "DocumentTemplate",  # noqa:F821
            List["DocumentTemplate"],  # noqa:F821
        ],
        document_id: Union[str, None] = None,
    ):
        """DEPRECATED

        Perform diff on 2 set of document(s), result in a Patch object.

        Do not connect when using public API.

        Returns
        -------
        obj
            Patch object

        Examples
        --------
        >>> client = Client("http://127.0.0.1:6363/")
        >>> client.connect(user="admin", key="root", team="admin", db="some_db")
        >>> result = client.diff({ "@id" : "Person/Jane", "@type" : "Person", "name" : "Jane"}, { "@id" : "Person/Jane", "@type" : "Person", "name" : "Janine"})
        >>> result.to_json = '{ "name" : { "@op" : "SwapValue", "@before" : "Jane", "@after": "Janine" }}'"""

        request_dict = {}
        for key, item in {"before": before, "after": after}.items():
            if isinstance(item, str):
                request_dict[f"{key}_data_version"] = item
            else:
                request_dict[key] = self._convert_diff_document(item)
        if document_id is not None:
            if "before_data_version" in request_dict:
                if document_id[: len("terminusdb:///data")] == "terminusdb:///data":
                    request_dict["document_id"] = document_id
                else:
                    raise ValueError(
                        f"Valid document id starts with `terminusdb:///data`, but got {document_id}"
                    )
            else:
                raise ValueError(
                    "`document_id` can only be used in conjusction with a data version or commit ID as `before`, not a document object"
                )
        if self._connected:
            result = _finish_response(
                self._session.post(
                    self._diff_url(),
                    headers=self._default_headers,
                    json=request_dict,
                    auth=self._auth(),
                )
            )
        else:
            result = _finish_response(
                requests.post(
                    self.server_url,
                    headers=self._default_headers,
                    json=request_dict,
                )
            )
        return Patch(json=result)

    def patch(
        self,
        before: Union[
            dict,
            List[dict],
            "Schema",  # noqa:F821
            "DocumentTemplate",  # noqa:F821
            List["DocumentTemplate"],  # noqa:F821
        ],
        patch: Patch,
    ):
        """Apply the patch object to the before object and return an after object. Note that this change does not commit changes to the graph.

        Do not connect when using public API.

        Parameters
        ----------
        before : dict
            Object before to patch
        patch : Patch
            Patch object to apply to the dict

        Returns
        -------
        dict
            After object

        Examples
        --------
        >>> client = Client("http://127.0.0.1:6363/")
        >>> client.connect(user="admin", key="root", team="admin", db="some_db")
        >>> patch_obj = Patch(json='{"name" : { "@op" : "ValueSwap", "@before" : "Jane", "@after": "Janine" }}')
        >>> result = client.patch({ "@id" : "Person/Jane", "@type" : Person", "name" : "Jane"}, patch_obj)
        >>> print(result)
        '{ "@id" : "Person/Jane", "@type" : Person", "name" : "Janine"}'"""

        request_dict = {
            "before": self._convert_diff_document(before),
            "patch": patch.content,
        }

        if self._connected:
            result = _finish_response(
                self._session.post(
                    self._patch_url(),
                    headers=self._default_headers,
                    json=request_dict,
                    auth=self._auth(),
                )
            )
        else:
            result = _finish_response(
                requests.post(
                    self.server_url,
                    headers=self._default_headers,
                    json=request_dict,
                )
            )
        return json.loads(result)

    def patch_resource(
        self,
        patch: Patch,
        branch=None,
        message=None,
        author=None,
        match_final_state=True,
    ):
        """Apply the patch object to the given resource

        Do not connect when using public API.

        Returns
        -------
        dict
            After object

        Examples
        --------
        >>> client = Client("http://127.0.0.1:6363/")
        >>> client.connect(user="admin", key="root", team="admin", db="some_db")
        >>> patch_obj = Patch(json='{"name" : { "@op" : "ValueSwap", "@before" : "Jane", "@after": "Janine" }}')
        >>> result = client.patch_resource(patch_obj,branch="main")
        >>> print(result)
        '["Person/Jane"]'"""
        commit_info = self._generate_commit(message, author)
        request_dict = {
            "patch": patch.content,
            "message" : commit_info["message"],
            "author" : commit_info["author"],
            "match_final_state" : match_final_state
        }
        patch_url = self._branch_base("patch", branch)

        result = _finish_response(
            self._session.post(
                patch_url,
                headers=self._default_headers,
                json=request_dict,
                auth=self._auth(),
            )
        )
        return json.loads(result)

    def clonedb(
            self, clone_source: str, newid: str, description: Optional[str] = None,
            remote_auth: Optional[dict] = None
    ) -> None:
        """Clone a remote repository and create a local copy.

        Parameters
        ----------
        clone_source : str
            The source url of the repo to be cloned.
        newid : str
            Identifier of the new repository to create.
        Description : str, optional
            Optional description about the cloned database.
        remote_auth : str, optional
            Optional remote authorization (uses client remote auth otherwise)

        Raises
        ------
        InterfaceError
            if the client does not connect to a database

        Examples
        --------
        >>> client = Client("http://127.0.0.1:6363/")
        >>> client.clonedb("http://terminusdb.com/some_user/test_db", "my_test_db")
        """
        self._check_connection(check_db=False)
        if description is None:
            description = f"New database {newid}"

        if self._remote_auth_dict or remote_auth:
            headers = {'Authorization-Remote' : self._generate_remote_header(remote_auth) if remote_auth else self._remote_auth()}
        headers.update(self._default_headers)
        rc_args = {"remote_url": clone_source, "label": newid, "comment": description}

        _finish_response(
            self._session.post(
                self._clone_url(newid),
                headers=headers,
                json=rc_args,
                auth=self._auth(),
            )
        )

    def _generate_commit(
        self, msg: Optional[str] = None, author: Optional[str] = None
    ) -> dict:
        """Pack the specified commit info into a dict format expected by the server.

        Parameters
        ----------
        msg : str
            Commit message.
        author : str
            Commit author.

        Returns
        -------
        dict
            Formatted commit info.

        Examples
        --------
        >>> client = Client("http://127.0.0.1:6363/")
        >>> client._generate_commit("<message>", "<author>")
        {'author': '<author>', 'message': '<message>'}
        """
        if author:
            mes_author = author
        else:
            mes_author = self._author
        if not msg:
            msg = f"Commit via python client {__version__}"
        return {"author": mes_author, "message": msg}

    def _auth(self):
        # if https basic
        if not self._use_token and self._connected and self._key and self.user:
            return (self.user, self._key)
        elif self._connected and self._jwt_token is not None:
            return JWTAuth(self._jwt_token)
        elif self._connected and self._api_token is not None:
            return APITokenAuth(self._api_token)
        elif self._connected:
            return APITokenAuth(os.environ["TERMINUSDB_ACCESS_TOKEN"])
        else:
            raise RuntimeError("Client not connected.")

    def _remote_auth(self):
        if self._remote_auth_dict:
            return self._generate_remote_header(self._remote_auth_dict)
        elif "TERMINUSDB_REMOTE_ACCESS_TOKEN" in os.environ:
            token = os.environ["TERMINUSDB_REMOTE_ACCESS_TOKEN"]
            return f"Token {token}"

    def _generate_remote_header(self, remote_auth: dict):
        key_type = remote_auth['type']
        key = remote_auth['key']
        if key_type == 'http_basic':
            username = remote_auth['username']
            http_basic_creds = base64.b64encode(f"{username}:{key}".encode('utf-8'))
            return f"Basic {http_basic_creds}"
        elif key_type == 'token':
            return f"Token {key}"
        # JWT is the only key type remaining
        return f"Bearer {key}"

    def create_organization(self, org: str) -> Optional[dict]:
        """
        Add a new organization

        Parameters
        ----------
        org : str
            The id of the organization

        Raises
        ------
        InterfaceError
            if the client does not connect to a server

        Returns
        -------
        dict or None if failed
        """
        self._check_connection(check_db=False)
        result = self._session.post(
            f"{self._organization_url()}/{org}",
            headers=self._default_headers,
            auth=self._auth(),
        )
        return json.loads(_finish_response(result))

    def get_organization_users(self, org: str) -> Optional[dict]:
        """
        Returns a list of users in an organization.

        Parameters
        ----------
        org : str

        Raises
        ------
        InterfaceError
            if the client does not connect to a server

        Returns
        -------
        dict or None if not found

        """
        self._check_connection(check_db=False)
        result = self._session.get(
            f"{self._organization_url()}/{org}/users",
            headers=self._default_headers,
            auth=self._auth(),
        )
        return json.loads(_finish_response(result))

    def get_organization_user(self, org: str, username: str) -> Optional[dict]:
        """
        Returns user info related to an organization.

        Parameters
        ----------
        org : str
        username : str

        Raises
        ------
        InterfaceError
            if the client does not connect to a server

        Returns
        -------
        dict or None if not found

        """
        self._check_connection(check_db=False)
        result = self._session.get(
            f"{self._organization_url()}/{org}/users/{username}",
            headers=self._default_headers,
            auth=self._auth(),
        )
        return json.loads(_finish_response(result))

    def get_organization_user_databases(self, org: str, username: str) -> Optional[dict]:
        """
        Returns the databases available to a user which are inside an organization

        Parameters
        ----------
        org : str
        username : str

        Raises
        ------
        InterfaceError
            if the client does not connect to a server

        Returns
        -------
        dict or None if not found

        """
        self._check_connection(check_db=False)
        result = self._session.get(
            f"{self._organization_url()}/{org}/users/{username}/databases",
            headers=self._default_headers,
            auth=self._auth(),
        )
        return json.loads(_finish_response(result))

    def get_organizations(self) -> Optional[dict]:
        """
        Returns a list of organizations in the database.

        Raises
        ------
        InterfaceError
            if the client does not connect to a server

        Returns
        -------
        dict or None if not found

        """
        self._check_connection(check_db=False)
        result = self._session.get(
            self._organization_url(),
            headers=self._default_headers,
            auth=self._auth(),
        )
        return json.loads(_finish_response(result))

    def get_organization(self, org: str) -> Optional[dict]:
        """
        Returns a specific organization

        Parameters
        ----------
        org : str
            The id of the organization

        Raises
        ------
        InterfaceError
            if the client does not connect to a server

        Returns
        -------
        dict or None if not found
        """
        self._check_connection(check_db=False)
        result = self._session.get(
            f"{self._organization_url()}/{org}",
            headers=self._default_headers,
            auth=self._auth(),
        )
        return json.loads(_finish_response(result))

    def delete_organization(self, org: str) -> Optional[dict]:
        """
        Deletes a specific organization

        Parameters
        ----------
        org : str
            The id of the organization

        Raises
        ------
        InterfaceError
            if the client does not connect to a server

        Returns
        -------
        dict or None if request failed
        """
        self._check_connection(check_db=False)
        result = self._session.delete(
            f"{self._organization_url()}/{org}",
            headers=self._default_headers,
            auth=self._auth(),
        )
        return json.loads(_finish_response(result))

    def change_capabilities(self, capability_change: dict) -> Optional[dict]:
        """
        Change the capabilities of a certain user

        Parameters
        ----------
        capability_change : dict
            Dict for the capability change request.

            Example:
            {
             "operation": "revoke",
             "scope": "UserDatabase/f5a0ef94469b32e1aee321678436c7dfd5a96d9c476672b3282ae89a45b5200e",
             "user": "User/admin",
             "roles": [
                 "Role/consumer",
                 "Role/admin"
              ]
            }

        Raises
        ------
        InterfaceError
            if the client does not connect to a server

        Returns
        -------
        dict or None if request failed

        """
        self._check_connection(check_db=False)
        result = self._session.post(
            f"{self._capabilities_url()}",
            headers=self._default_headers,
            json=capability_change,
            auth=self._auth(),
        )
        return json.loads(_finish_response(result))

    def add_role(self, role: dict) -> Optional[dict]:
        """
        Add a new role

        Parameters
        ----------
        role : dict
            The role dict

        Raises
        ------
        InterfaceError
            if the client does not connect to a server

        Returns
        -------
        dict or None if failed

        Examples
        --------
        >>> client = Client("http://127.0.0.1:6363")
        >>> client.connect(key="root", team="admin", user="admin", db="example_db")
        >>> role = {
            "name": "Grand Pubah",
            "action": [
                "branch",
                "class_frame",
                "clone",
                "commit_read_access",
                "commit_write_access",
                "create_database",
                "delete_database",
                "fetch",
                "instance_read_access",
                "instance_write_access",
                "manage_capabilities",
                "meta_read_access",
                "meta_write_access",
                "push",
                "rebase",
                "schema_read_access",
                "schema_write_access"
              ]
          }
        >>> client.add_role(role)
        """
        self._check_connection(check_db=False)
        result = self._session.post(
            f"{self._roles_url()}",
            headers=self._default_headers,
            json=role,
            auth=self._auth(),
        )
        return json.loads(_finish_response(result))

    def change_role(self, role: dict) -> Optional[dict]:
        """
        Change role actions for a particular role

        Parameters
        ----------
        role : dict
            Role dict


        Raises
        ------
        InterfaceError
            if the client does not connect to a server

        Returns
        -------
        dict or None if failed

        Examples
        --------
        >>> client = Client("http://127.0.0.1:6363")
        >>> client.connect(key="root", team="admin", user="admin", db="example_db")
        >>> role = {
            "name": "Grand Pubah",
            "action": [
                "branch",
                "class_frame",
                "clone",
                "commit_read_access",
                "commit_write_access",
                "create_database",
                "delete_database",
                "fetch",
                "instance_read_access",
                "instance_write_access",
                "manage_capabilities",
                "meta_read_access",
                "meta_write_access",
                "push",
                "rebase",
                "schema_read_access",
                "schema_write_access"
              ]
          }
        >>> client.change_role(role)
        """
        self._check_connection(check_db=False)
        result = self._session.put(
            f"{self._roles_url()}",
            headers=self._default_headers,
            json=role,
            auth=self._auth(),
        )
        return json.loads(_finish_response(result))

    def get_available_roles(self) -> Optional[dict]:
        """
        Get the available roles for the current authenticated user

        Raises
        ------
        InterfaceError
            if the client does not connect to a server

        Returns
        -------
        dict or None if failed
        """
        self._check_connection(check_db=False)
        result = self._session.get(
            f"{self._roles_url()}",
            headers=self._default_headers,
            auth=self._auth(),
        )
        return json.loads(_finish_response(result))

    def add_user(self, username: str, password: str) -> Optional[dict]:
        """
        Add a new user

        Parameters
        ----------
        username : str
            The username of the user
        password : str
            The user's password

        Raises
        ------
        InterfaceError
            if the client does not connect to a server

        Returns
        -------
        dict or None if failed
        """
        self._check_connection(check_db=False)
        result = self._session.post(
            f"{self._users_url()}",
            headers=self._default_headers,
            json={"name": username, "password": password},
            auth=self._auth(),
        )
        return json.loads(_finish_response(result))

    def get_user(self, username: str) -> Optional[dict]:
        """
        Get a user

        Parameters
        ----------
        username : str
            The username of the user

        Raises
        ------
        InterfaceError
            if the client does not connect to a server

        Returns
        -------
        dict or None if failed
        """
        self._check_connection(check_db=False)
        result = self._session.get(
            f"{self._users_url()}/{username}",
            headers=self._default_headers,
            auth=self._auth(),
        )
        return json.loads(_finish_response(result))

    def get_users(self) -> Optional[dict]:
        """
        Get all users

        Raises
        ------
        InterfaceError
            if the client does not connect to a server

        Returns
        -------
        dict or None if failed
        """
        self._check_connection(check_db=False)
        result = self._session.get(
            f"{self._users_url()}",
            headers=self._default_headers,
            auth=self._auth(),
        )
        return json.loads(_finish_response(result))

    def delete_user(self, username: str) -> Optional[dict]:
        """
        Delete a user

        Parameters
        ----------
        username : str
            The username of the user

        Raises
        ------
        InterfaceError
            if the client does not connect to a server

        Returns
        -------
        dict or None if failed
        """
        self._check_connection(check_db=False)
        result = self._session.delete(
            f"{self._users_url()}/{username}",
            headers=self._default_headers,
            auth=self._auth(),
        )
        return json.loads(_finish_response(result))

    def change_user_password(self, username: str, password: str) -> Optional[dict]:
        """
        Change user's password

        Parameters
        ----------
        username : str
            The username of the user
        password : str
            The new password

        Raises
        ------
        InterfaceError
            if the client does not connect to a server

        Returns
        -------
        dict or None if failed
        """
        self._check_connection(check_db=False)
        result = self._session.put(
            f"{self._users_url()}",
            headers=self._default_headers,
            json={"name": username, "password": password},
            auth=self._auth(),
        )
        return json.loads(_finish_response(result))

    def get_database(self, dbid: str, team: Optional[str] = None) -> Optional[dict]:
        """
        Returns metadata (id, organization, label, comment) about the requested database
        Parameters
        ----------
        dbid : str
            The id of the database
        team : str
            The organization of the database (default self.team)

        Raises
        ------
        InterfaceError
            if the client does not connect to a server
        DatabaseError
            if the database can't be found

        Returns
        -------
        dict
        """
        self._check_connection(check_db=False)
        team = team if team else self.team
        result = self._session.get(
            f"{self.api}/db/{team}/{dbid}?verbose=true",
            headers=self._default_headers,
            auth=self._auth(),
        )
        return json.loads(_finish_response(result))

    def has_database(self, dbid: str, team: Optional[str] = None) -> bool:
        """
        Check whether a database exists

        Parameters
        ----------
        dbid : str
            The id of the database
        team : str
            The organization of the database (default self.team)

        Raises
        ------
        InterfaceError
            if the client does not connect to a server

        Returns
        -------
        True or False if not found
        """
        self._check_connection(check_db=False)
        team = team if team else self.team
        r = self._session.head(
            f"{self.api}/db/{team}/{dbid}",
            headers=self._default_headers,
            auth=self._auth(),
        )
        return r.status_code == 200

    def get_databases(self) -> List[dict]:
        """
        Returns a list of database metadata records for all databases the user has access to

        Raises
        ------
        InterfaceError
            if the client does not connect to a server

        Returns
        -------
        list of dicts
        """
        self._check_connection(check_db=False)

        result = self._session.get(
            self.api + "/",
            headers=self._default_headers,
            auth=self._auth(),
        )
        return json.loads(_finish_response(result))

    def list_databases(self) -> List[Dict]:
        """
        Returns a list of database ids for all databases the user has access to

        Raises
        ------
        InterfaceError
            if the client does not connect to a server

        Returns
        -------
        list of dicts
        """
        self._check_connection(check_db=False)
        all_dbs = []
        for data in self.get_databases():
            all_dbs.append(data["name"])
        return all_dbs

    def _db_url_fragment(self):
        if self._db == "_system":
            return self._db
        return f"{self._team}/{self._db}"

    def _db_base(self, action: str):
        return f"{self.api}/{action}/{self._db_url_fragment()}"

    def _branch_url(self, branch_id: str):
        base_url = self._repo_base("branch")
        branch_id = urlparse.quote(branch_id)
        return f"{base_url}/branch/{branch_id}"

    def _repo_base(self, action: str):
        return self._db_base(action) + f"/{self._repo}"

    def _branch_base(self, action: str, branch: Optional[str] = None):
        base = self._repo_base(action)
        if self._repo == "_meta":
            return base
        if self._branch == "_commits":
            return base + f"/{self._branch}"
        elif self.ref:
            return base + f"/commit/{self._ref}"
        elif branch:
            return base + f"/branch/{branch}"
        else:
            return base + f"/branch/{self._branch}"
        return base

    def _query_url(self):
        if self._db == "_system":
            return self._db_base("woql")
        return self._branch_base("woql")

    def _class_frame_url(self):
        if self._db == "_system":
            return self._db_base("schema")
        return self._branch_base("schema")

    def _capabilities_url(self):
        return f"{self.api}/capabilities"

    def _organization_url(self):
        return f"{self.api}/organizations"

    def _users_url(self):
        return f"{self.api}/users"

    def _roles_url(self):
        return f"{self.api}/roles"

    def _documents_url(self):
        if self._db == "_system":
            base_url = self._db_base("document")
        else:
            base_url = self._branch_base("document")
        return base_url

    def _triples_url(self, graph_type: GraphType = GraphType.INSTANCE):
        if self._db == "_system":
            base_url = self._db_base("triples")
        else:
            base_url = self._branch_base("triples")
        return f"{base_url}/{graph_type}"

    def _clone_url(self, new_repo_id: str):
        new_repo_id = urlparse.quote(new_repo_id)
        return f"{self.api}/clone/{self._team}/{new_repo_id}"

    def _cloneable_url(self):
        crl = f"{self.server_url}/{self._team}/{self._db}"
        return crl

    def _pull_url(self):
        return self._branch_base("pull")

    def _fetch_url(self, remote_name: str):
        furl = self._branch_base("fetch")
        remote_name = urlparse.quote(remote_name)
        return furl + "/" + remote_name + "/_commits"

    def _rebase_url(self):
        return self._branch_base("rebase")

    def _reset_url(self):
        return self._branch_base("reset")

    def _optimize_url(self, path: str):
        path = urlparse.quote(path)
        return f"{self.api}/optimize/{path}"

    def _squash_url(self):
        return self._branch_base("squash")

    def _diff_url(self):
        return self._branch_base("diff")

    def _apply_url(self, branch: Optional[str] = None):
        return self._branch_base("apply", branch)

    def _patch_url(self):
        return f"{self.api}/patch"

    def _push_url(self):
        return self._branch_base("push")

    def _db_url(self):
        return self._db_base("db")
