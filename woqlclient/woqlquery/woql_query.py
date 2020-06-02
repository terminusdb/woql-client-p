import re

from .woql_builder import TripleBuilder
from .woql_core import WOQLCore


class WOQLQuery(WOQLCore):
    def __init__(self, query=None):
        """defines the internal functions of the woql query object - the language API is defined in WOQLQuery

        Parameters
        ----------
        query json-ld query for initialisation"""
        super().__init__(query)
        # alias
        self.subsumption = self.sub
        self.equals = self.eq
        self.substring = self.substr
        self.update = self.update_object
        self.delete - self.delete_object
        self.read = self.read_object
        self.optional = self.opt
        self.idgenerator = self.idgen
        self.concatenate = self.concat
        self.typecast = self.cast

    def load_vocabulary(self, client):
        """Queries the schema graph and loads all the ids found there as vocabulary that can be used without prefixes
        ignoring blank node ids"""
        new_woql = WOQLQuery().quad("v:S", "v:P", "v:O", "schema/*")
        result = new_woql.execute(client)
        bindings = result.get("bindings", [])
        for each_result in bindings:
            for item in each_result:
                if type(item) == str:
                    spl = item.split(":")
                    if len(spl) == 2 and spl[1] and spl[0] != "_":
                        self._vocab[spl[0]] = spl[1]

    def _wrap_cursor_with_and(self):
        new_json = WOQLQuery().json(self._cursor)
        for item in self._curser:
            del self._cursor[item]
        self.woql_and(new_json, {})
        self._cursor = self._cursor["woql:query_list"][1]["woql:query"]

    def using(self, collection, subq):
        if collection and collection == "woql:args":
            return ["woql:collection", "woql:query"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:Using"
        if not collection or type(collection) != str:
            return self._parameter_error(
                "The first parameter to using must be a Collection ID (string)"
            )
        self._cursor["woql:collection"] = self._jlt(collection)
        return self._add_sub_query(subq)

    def comment(self, comment, subq):
        if comment and comment == "woql:args":
            return ["woql:comment", "woql:query"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:Comment"
        self._cursor["woql:comment"] = self._jlt(comment)
        return self._add_sub_query(subq)

    def select(self, *args):
        queries = list(args)
        if queries and queries[0] == "woql:args":
            return ["woql:variable_list", "woql:query"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:Select"
        if not queries:
            return self._parameter_error(
                "Select must be given a list of variable names"
            )
        if type(queries[-1]) not in [bool, str, int, float] and hasattr(
            queries[-1], "json"
        ):
            embedquery = queries.pop()
        else:
            embedquery = False
        self._cursor["woql:variable_list"] = []
        for idx, item in enumerate(queries):
            onevar = self._varj(item)
            onevar["@type"] = "woql:VariableListElement"
            onevar["woql:index"] = self._jlt(idx, "nonNegativeInteger")
            self._cursor["woql:variable_list"].append(onevar)
        return self._add_sub_query(embedquery)

    def woql_and(self, *args):
        queries = list(args)
        if self._cursor.get("@type") and self._cursor["@type"] != "woql:And":
            new_json = WOQLQuery().json(self._cursor)
            for key in self._cursor:
                del self._cursor[key]
            queries = [new_json] + queries
        if queries and queries[0] == "woql:args":
            return ["woql:query_list"]
        self._cursor["@type"] = "woql:And"
        if "woql:query_list" not in self._cursor:
            self._cursor["woql:query_list"] = []
        for item in queries:
            index = len(self._cursor["woql:query_list"])
            onevar = self._gle(item, index)
            if (
                onevar["woql:query"]["@type"] == "woql:And"
                and onevar["woql:query"]["woql:query_list"]
            ):
                for each in onevar["woql:query"]["woql:query_list"]:
                    qjson = each["woql:query"]
                if qjson:
                    index = len(self._cursor["woql:query_list"])
                    subvar = self._qle(qjson, index)
                    self._cursor["woql:query_list"].append(subvar)
            else:
                self._cursor["woql:query_list"].append(onevar)
        return self

    def woql_or(self, *args):
        queries = list(args)
        if queries and queries[0] == "woql:args":
            return ["woql:query_list"]
        if self._cursor.get("@type") and self._cursor["@type"] != "woql:Or":
            new_json = WOQLQuery().json(self._cursor)
            for key in self._cursor:
                del self._cursor[key]
            queries = [new_json] + queries
        self._cursor["@type"] = "woql:Or"
        if "woql:query_list" not in self._cursor:
            self._cursor["woql:query_list"] = []
        for idx, item in enumerate(queries):
            onevar = self._qle(item, idx)
            self._cursor["woql:query_list"].append(onevar)
        return self

    def woql_from(self, graph_filter, query):
        if graph_filter and graph_filter == "woql:args":
            return ["woql:graph_filter", "woql:query"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:From"
        if not graph_filter or type(graph_filter) != str:
            return self._parameter_error(
                "The first parameter to from must be a Graph Filter Expression (string)"
            )
        self._cursor["woql:graph_filter"] = self._jlt(graph_filter)
        return self._add_sub_query(query)

    def into(self, graph_descriptor, query):
        if graph_descriptor and graph_descriptor == "woql:args":
            return ["woql:graph", "woql:query"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:Into"
        if not graph_descriptor or type(graph_descriptor) != str:
            return self._parameter_error(
                "The first parameter to from must be a Graph Filter Expression (string)"
            )
        self._cursor["woql:graph"] = self._jlt(graph_descriptor)
        return self._add_sub_query(query)

    def triple(self, sub, pred, obj):
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:Triple"
        self._cursor["woql:subject"] = self._clean_subject(sub)
        self._cursor["woql:predicate"] = self._clean_predicate(pred)
        self._cursor["woql:object"] = self._clean_object(obj)
        return self

    def quad(self, sub, pred, obj, graph):
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        arguments = self.triple(sub, pred, obj)
        if sub and sub == "woql:args":
            return arguments.concat(["woql:graph_filter"])
        if not graph:
            return self._parameter_error(
                "Quad takes four parameters, the last should be a graph filter"
            )
        self._cursor["@type"] = "woql:Quad"
        self._cursor["woql:graph_filter"] = self._clean_graph(graph)
        return self

    def sub(self, parent, child):
        if parent and parent == "woql:args":
            return ["woql:parent", "woql:child"]
        if parent is None or child is None:
            return self._parameter_error("Subsumption takes two parameters, both URIs")
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:Subsumption"
        self._cursor["woql:parent"] = self._clean_class(parent)
        self._cursor["woql:child"] = self._clean_class(child)
        return self

    def eq(self, left, right):
        if left and left == "woql:args":
            return ["woql:left", "woql:right"]
        if left is None or right is None:
            return self.self._parameter_error("Equals takes two parameters")
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:Equals"
        self._cursor["woql:left"] = self._clean_class(left)
        self._cursor["woql:right"] = self._clean_class(right)

    def substr(self, string, length, substring, before=0, after=0):
        if string and string == "woql:args":
            return [
                "woql:string",
                "woql:before",
                "woql:length",
                "woql:after",
                "woql:substring",
            ]
        if not substring:
            substring = length
            length = len(substring) + before
        if not string or not substring or type(substring) != type:
            return self._parameter_error(
                "Substr - the first and last parameters must be strings representing the full and substring variables / literals"
            )
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:Substring"
        self._cursor["woql:string"] = self._clean_object(string)
        self._cursor["woql:before"] = self._clean_object(
            before, "xsd:nonNegativeInteger"
        )
        self._cursor["woql:length"] = self._clean_object(
            length, "xsd:nonNegativeInteger"
        )
        self._cursor["woql:after"] = self._clean_object(after, "xsd:nonNegativeInteger")
        self._cursor["woql:substring"] = self._clean_object(substring)
        return self

    def update_object(self, docjson):
        if docjson and docjson == "woql:args":
            return ["woql:document"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:UpdateObject"
        self._cursor["woql:document"] = docjson
        return self._updated()

    def delete_object(self, json_or_iri):
        if json_or_iri and json_or_iri == "woql:args":
            return ["woql:document"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:DeleteObject"
        self._cursor["woql:document_uri"] = json_or_iri
        return self._updated()

    def read_object(self, iri, output_var, out_format):
        if iri and iri == "woql:args":
            return ["woql:document"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:ReadObject"
        self._cursor["woql:document_uri"] = iri
        self._cursor["woql:document"] = self._expand_variable(output_var)
        return self._wfroms(out_format)

    def get(self, as_vars, query_resource):
        """Takes an as structure"""
        if as_vars and as_vars == "woql:args":
            return ["woql:as_vars", "woql:query_resource"]
        self._cursor["@type"] = "woql:Get"
        if hasattr(as_vars, "json"):
            self._cursor["woql:as_vars"] = as_vars.json()
        else:
            self._cursor["woql:as_vars"] = WOQLQuery().woql_as(*as_vars).json()
        if query_resource:
            self._cursor["woql:query_resource"] = self._jobj(query_resource)
        else:
            self._cursor["woql:query_resource"] = {}
        self._cursor = self._cursor["woql:query_resource"]
        return self

    def put(self, as_vars, query_resource, query):
        """Takes an array of variables, an optional array of column names"""
        if as_vars and as_vars == "woql:args":
            return ["woql:as_vars", "woql:query", "woql:query_resource"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:Put"
        if hasattr(as_vars, "json"):
            self._cursor["woql:as_vars"] = as_vars.json()
        else:
            self._cursor["woql:as_vars"] = WOQLQuery().woql_as(*as_vars).json()
        if query_resource:
            self._cursor["woql:query_resource"] = self._jobj(query_resource)
        else:
            self._cursor["woql:query_resource"] = {}
        return self._add_sub_query(query)

    def woql_as(self, *args):
        if args and args[0] == "woql:args":
            return [["woql:indexed_as_var", "woql:named_as_var"]]
        if type(self._query) != list:
            self._query = []
        if type(args[0]) == list:
            for onemap in args:
                if type(onemap) == list and len(onemap) >= 2:
                    if len(onemap) == 2:
                        map_type = False
                    else:
                        map_type = onemap[2]
                    oasv = self._asv(onemap[0], onemap[1], map_type)
                    self._query.append(oasv)
        elif type(args[0]) in [float, str]:
            if len(args) > 2:
                map_type = args[2]
            else:
                map_type = False
            oasv = self._asv(args[0], args[1], type)
            self._query.append(oasv)
        elif type(args[0]) == dict:
            if hasattr(args[0], "json"):
                self._query.append(args[0].json)
            else:
                self._query.append(args[0])
        return self

    def file(self, fpath, opts):
        if fpath and fpath == "woql:args":
            return ["woql:file", "woql:format"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:FileResource"
        self._cursor["woql:file"] = fpath
        return self._wfrom(opts)

    def remote(self, uri, opts):
        if uri and uri == "woql:args":
            return ["woql:remote_uri", "woql:format"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:RemoteResource"
        self._cursor["woql:remote_uri"] = {"@type": "xsd:anyURI", "@value": uri}
        return self._wfrom(opts)

    def post(self, fpath, opts):
        if fpath and fpath == "woql:args":
            return ["woql:file", "woql:format"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:PostResource"
        self._cursor["woql:file"] = {"@type": "xsd:string", "@value": fpath}
        return self._wfrom(opts)

    def delete_triple(self, subject, predicate, object_or_literal):
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        triple_args = self.triple(subject, predicate, object_or_literal)
        if subject and subject == "woql:args":
            return triple_args
        self._cursor["@type"] = "woql:DeleteTriple"
        return self._updated()

    def add_triple(self, subject, predicate, object_or_literal):
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        triple_args = self.triple(subject, predicate, object_or_literal)
        if subject and subject == "woql:args":
            return triple_args
        self._cursor["@type"] = "woql:AddTriple"
        return self._updated()

    def delete_quad(self, subject, predicate, object_or_literal, graph):
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        triple_args = self.triple(subject, predicate, object_or_literal)
        if subject and subject == "woql:args":
            return triple_args.concat(["woql:graph"])
        if not graph:
            return self._parameter_error(
                "Delete Quad takes four parameters, the last should be a graph id"
            )
        self._cursor["@type"] = "woql:DeleteQuad"
        self._cursor["woql:graph"] = self._clean_graph(graph)
        return self._updated()

    def add_quad(self, subject, predicate, object_or_literal, graph):
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        triple_args = self.triple(subject, predicate, object_or_literal)
        if subject and subject == "woql:args":
            return triple_args.concat(["woql:graph"])
        if not graph:
            return self._parameter_error(
                "Delete Quad takes four parameters, the last should be a graph id"
            )
        self._cursor["@type"] = "woql:AddQuad"
        self._clean_graph(graph)
        return self._updated()

    def when(self, query, consequent=None):
        if query and query == "woql:args":
            return ["woql:query", "woql:consequent"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:When"
        self._add_sub_query(query)
        if consequent:
            self._cursor["woql:consequent"] = self._jobj(consequent)
        else:
            self._cursor["woql:consequent"] = {}
        self._cursor = self._cursor["woql:consequent"]
        return self

    def trim(self, untrimmed, trimmed):
        if untrimmed and untrimmed == "woql:args":
            return ["woql:untrimmed", "woql:trimmed"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:Trim"
        self._cursor["woql:untrimmed"] = self._clean_object(untrimmed)
        self._cursor["woql:trimmed"] = self._clean_object(trimmed)
        return self

    def eval(self, arith, res):
        if arith and arith == "woql:args":
            return ["woql:expression", "woql:result"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:Eval"
        if hasattr(arith, "json"):
            self._cursor["woql:expression"] = arith.json()
        else:
            self._cursor["woql:expression"] = arith
        self._cursor["woql:result"] = self._clean_object(res)
        return self

    def plus(self, *args):
        new_args = list(args)
        if new_args and new_args[0] == "woql:args":
            return ["woql:first", "woql:second"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:Plus"
        self._cursor["woql:first"] = self._arop(new_args.pop(0))
        if len(new_args > 1):
            self._cursor = self._jobj(WOQLQuery().plus(*args))
        else:
            self._cursor["woql:second"] = self._arop(args[0])
        return self

    def minus(self, *args):
        new_args = list(args)
        if new_args and new_args[0] == "woql:args":
            return ["woql:first", "woql:second"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:Minus"
        self._cursor["woql:first"] = self._arop(new_args.pop(0))
        if len(new_args) > 1:
            self._cursor["woql:second"] = self._jobj(WOQLQuery().minus(*new_args))
        else:
            self._cursor["woql:second"] = self._arop(args[0])
        return self

    def times(self, *args):
        new_args = list(args)
        if new_args and new_args[0] == "woql:args":
            return ["woql:first", "woql:second"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:Times"
        self._cursor["woql:first"] = self._arop(new_args.pop(0))
        if len(new_args) > 1:
            self._cursor["woql:second"] = self._jobj(WOQLQuery().times(*new_args))
        else:
            self._cursor["woql:second"] = self._arop(args[0])
        return self

    def divide(self, *args):
        new_args = list(args)
        if new_args and new_args[0] == "woql:args":
            return ["woql:first", "woql:second"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:Divide"
        self._cursor["woql:first"] = self._arop(new_args.pop(0))
        if len(new_args) > 1:
            self._cursor["woql:second"] = self._jobj(WOQLQuery().divide(*new_args))
        else:
            self._cursor["woql:second"] = self._arop(args[0])
        return self

    def div(self, *args):
        new_args = list(args)
        if new_args and new_args[0] == "woql:args":
            return ["woql:first", "woql:second"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:Div"
        self._cursor["woql:first"] = self._arop(new_args.pop(0))
        if len(new_args) > 1:
            self._cursor["woql:second"] = self._jobj(WOQLQuery().div(*new_args))
        else:
            self._cursor["woql:second"] = self._arop(args[0])
        return self

    def exp(self, first, second):
        if first and first == "woql:args":
            return ["woql:first", "woql:second"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
            self._cursor["@type"] = "woql:Exp"
        self._cursor["woql:first"] = self._arop(first)
        self._cursor["woql:second"] = self._arop(second)
        return self

    def floor(self, user_input):
        if user_input and user_input == "woql:args":
            return ["woql:argument"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:Floor"
        self._cursor["woql:argument"] = self._arop(user_input)
        return self

    def isa(self, element, of_type):
        if element and element == "woql:args":
            return ["woql:element", "woql:of_type"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:IsA"
        self._cursor["woql:element"] = self._clean_subject(element)
        self._cursor["woql:of_type"] = self._clean_class(of_type)
        return self

    def like(self, left, right, dist):
        if left and left == "woql:args":
            return ["woql:left", "woql:right", "woql:like_similarity"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:Like"
        self._cursor["woql:left"] = self._clean_object(left)
        self._cursor["woql:right"] = self._clean_object(right)
        if dist:
            self._cursor["woql:like_similarity"] = self._clean_object(
                dist, "xsd:decimal"
            )
        return self

    def less(self, left, right):
        if left and left == "woql:args":
            return ["woql:left", "woql:right"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:Less"
        self._cursor["woql:left"] = self._clean_object(left)
        self._cursor["woql:right"] = self._clean_object(right)
        return self

    def greater(self, left, right):
        if left and left == "woql:args":
            return ["woql:left", "woql:right"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:Greater"
        self._cursor["woql:left"] = self._clean_object(left)
        self._cursor["woql:right"] = self._clean_object(right)
        return self

    def opt(self, query):
        if query and query == "woql:args":
            return ["woql:query"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:Optional"
        self._add_sub_query(query)
        return self

    def unique(self, prefix, key_list, uri):
        if prefix and prefix == "woql:args":
            return ["woql:base", "woql:key_list", "woql:uri"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:Unique"
        self._cursor["woql:base"] = self._clean_object(prefix)
        self._cursor["woql:key_list"] = self._vlist(key_list)
        self._cursor["woql:uri"] = self._clean_class(uri)
        return self

    def idgen(self, prefix, input_var_list, output_var):
        if prefix and prefix == "woql:args":
            return ["woql:base", "woql:key_list", "woql:uri"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:IDGenerator"
        self._cursor["woql:base"] = self._clean_object(prefix)
        self._cursor["woql:key_list"] = self._vlist(input_var_list)
        self._cursor["woql:uri"] = self._clean_class(output_var)
        return self

    def upper(self, left, right):
        if left and left == "woql:args":
            return ["woql:left", "woql:right"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:Upper"
        self._cursor["woql:left"] = self._clean_object(left)
        self._cursor["woql:right"] = self._clean_object(right)
        return self

    def lower(self, left, right):
        if left and left == "woql:args":
            return ["woql:left", "woql:right"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:Lower"
        self._cursor["woql:left"] = self._clean_object(left)
        self._cursor["woql:right"] = self._clean_object(right)
        return self

    def pad(self, user_input, pad, length, output):
        if user_input and user_input == "woql:args":
            return [
                "woql:pad_string",
                "woql:pad_char",
                "woql:pad_times",
                "woql:pad_result",
            ]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:Pad"
        self._cursor["woql:pad_string"] = self._clean_object(user_input)
        self._cursor["woql:pad_char"] = self._clean_object(pad)
        self._cursor["woql:pad_times"] = self._clean_object(length, "xsd:integer")
        self._cursor["woql:pad_result"] = self._clean_object(output)
        return self

    def split(self, user_input, glue, output):
        if user_input and user_input == "woql:args":
            return ["woql:split_string", "woql:split_pattern", "woql:split_list"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:Split"
        self._cursor["woql:split_string"] = self._clean_object(user_input)
        self._cursor["woql:split_pattern"] = self._clean_object(glue)
        self._cursor["woql:split_list"] = self._wlist(output)
        return self

    def member(self, member, mem_list):
        if member and member == "woql:args":
            return ["woql:member", "woql:member_list"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:Member"
        self._cursor["woql:member"] = self._clean_object(member)
        self._cursor["woql:member_list"] = self._wlist(mem_list)
        return self

    def concat(self, concat_list, result):
        if concat_list and concat_list == "woql:args":
            return ["woql:concat_list", "woql:concatenated"]
        if type(concat_list) == str:
            slist = re.split("(v:)", concat_list)
            nlist = []
            if slist[0]:
                nlist.append(slist[0])
            for idx, item in enumerate(slist):
                if item and item == "v:":
                    slist2 = re.split(r"[^\w_]", slist[idx + 1])
                    x_var = slist2.pop(0)
                    nlist.push("v:" + x_var)
                    rest = "".join(slist2)
                    if rest:
                        nlist.append(rest)
            concat_list = nlist
        if type(concat_list) == list:
            if self._cursor.get("@type"):
                self._wrap_cursor_with_and()
            self._cursor["@type"] = "woql:Concatenate"
            self._cursor["woql:concat_list"] = self._wlist(concat_list)
            self._cursor["woql:concatenated"] = self._clean_object(result)
        return self

    def join(self, user_input, glue, output):
        if user_input and user_input == "woql:args":
            return ["woql:join_list", "woql:join_separator", "woql:join"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:Join"
        self._cursor["woql:join_list"] = self._wlist(user_input)
        self._cursor["woql:join_separator"] = self._clean_object(glue)
        self._cursor["woql:join"] = self._clean_object(output)
        return self

    def sum(self, user_input, output):
        if user_input and user_input == "woql:args":
            return ["woql:sum_list", "woql:sum"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:Sum"
        self._cursor["woql:sum_list"] = self._wlist(user_input)
        self._cursor["woql:sum"] = self._clean_object(output)
        return self

    def start(self, start, query):
        if start and start == "woql:args":
            return ["woql:start", "woql:query"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:Start"
        self._cursor["woql:start"] = self._clean_object(start, "xsd:nonNegativeInteger")
        return self._add_sub_query(query)

    def limit(self, limit, query):
        if limit and limit == "woql:args":
            return ["woql:limit", "woql:query"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:Limit"
        self._cursor["woql:limit"] = self._clean_object(limit, "xsd:nonNegativeInteger")
        return self._add_sub_query(query)

    def re(self, pattern, reg_str, reg_list):
        if pattern and pattern == "woql:args":
            return ["woql:pattern", "woql:regexp_string", "woql:regexp_list"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:Regexp"
        self._cursor["woql:pattern"] = self._clean_object(pattern)
        self._cursor["woql:regexp_string"] = self._clean_object(reg_str)
        self._cursor["woql:regexp_list"] = self._wlist(reg_list)
        return self

    def length(self, var_list, var_len):
        if var_list and var_list == "woql:args":
            return ["woql:length_list", "woql:length"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:Length"
        self._cursor["woql:length_list"] = self._vlist(var_list)
        if type(var_len) == float:
            self._cursor["woql:length"] = self._clean_object(
                var_len, "xsd:nonNegativeInteger"
            )
        elif type(var_len) == str:
            self._cursor["woql:length"] = self._varj(var_len)
        return self

    def woql_not(self, query):
        if query and query == "woql:args":
            return ["woql:query"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:Not"
        return self._add_sub_query(query)

    def cast(self, val, user_type, result):
        if val and val == "woql:args":
            return ["woql:typecast_value", "woql:typecast_type", "woql:typecast_result"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:Typecast"
        self._cursor["woql:typecast_value"] = self._clean_object(val)
        self._cursor["woql:typecast_type"] = self._clean_object(user_type)
        self._cursor["woql:typecast_result"] = self._clean_object(result)
        return self

    def order_by(self, *args):
        ordered_varlist = list(args)
        if ordered_varlist and ordered_varlist == "woql:args":
            return ["woql:variable_ordering", "woql:query"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:OrderBy"
        self._cursor["woql:variable_ordering"] = []

        if not ordered_varlist or len(ordered_varlist) == 0:
            return self._parameter_error(
                "Order by must be passed at least one variables to order the query"
            )

        if type(ordered_varlist[-1]) == dict and hasattr(ordered_varlist[-1], "json"):
            embedquery = ordered_varlist.pop()
        else:
            embedquery = False
        for idx, item in enumerate(ordered_varlist):
            if type(item) == str:
                obj = {
                    "@type": "woql:VariableOrdering",
                    "woql:index": self._jlt(idx, "xsd:nonNegativeInteger"),
                }
                cmds = item.split(" ")
                if len(cmds) > 1 and cmds[1].strip().lower() == "asc":
                    obj["woql:ascending"] = self._jlt(True, "xsd:boolean")
                varname = cmds[0].strip()
                obj["woql:variable"] = self._varj(varname)
                self._cursor["woql:variable_ordering"].append(obj)
            else:
                self._cursor["woql:variable_ordering"].append(ordered_varlist[idx])
        return self._add_sub_query(embedquery)

    def group_by(self, gvarlist, groupedvar, output, groupquery):
        if gvarlist and gvarlist == "woql:args":
            return [
                "woql:variable_list",
                "woql:group_var",
                "woql:grouped",
                "woql:query",
            ]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:GroupBy"
        self._cursor["woql:group_by"] = []
        if type(gvarlist) == str:
            gvarlist = [gvarlist]
        for idx, item in enumerate(gvarlist):
            onevar = self._varj(item)
            onevar["@type"] = "woql:VariableListElement"
            onevar["woql:index"] = self._jlt(idx, "nonNegativeInteger")
            self._cursor["woql:group_by"].append(onevar)
        self._cursor["woql:group_template"] = []
        if type(groupedvar) == str:
            groupedvar = [groupedvar]
        for idx, item in enumerate(groupedvar):
            onevar = self._varj(item)
            onevar["@type"] = "woql:VariableListElement"
            onevar["woql:index"] = self._jlt(idx, "nonNegativeInteger")
            self._cursor["woql:group_template"].append(onevar)
        self._cursor["woql:grouped"] = self._varj(output)
        return self._add_sub_query(groupquery)

    def true(self, subject, pattern, obj, path):
        if subject and subject == "woql:args":
            return ["woql:subject", "woql:path_pattern", "woql:object", "woql:path"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:Path"
        self._cursor["woql:subject"] = self._clean_subject(subject)
        if type(pattern) == str:
            pattern = self._compile_path_pattern(pattern)
        self._cursor["woql:path_pattern"] = pattern
        self._cursor["woql:object"] = self._clean_object(obj)
        self._cursor["woql:path"] = self._varj(path)
        return self

    def size(self, graph, size):
        if graph and graph == "woql:args":
            return ["woql:resource", "woql:size"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:Size"
        self._cursor["woql:resource"] = self._clean_graph(graph)
        self._cursor["woql:size"] = self._varj(size)
        return self

    def triple_count(self, graph, triple_count):
        if graph and graph == "woql:args":
            return ["woql:resource", "woql:triple_count"]
        if self._cursor.get("@type"):
            self._wrap_cursor_with_and()
        self._cursor["@type"] = "woql:TripleCount"
        self._cursor["woql:resource"] = self._clean_graph(graph)
        self._cursor["woql:triple_count"] = self._varj(triple_count)
        return self

    def star(self, graph=None, subj=None, pred=None, obj=None):
        if subj is None:
            subj = "v:Subject"
        if pred is None:
            pred = "v:Predicate"
        if obj is None:
            obj = "v:Object"
        if graph is None:
            graph = False
        if graph is not None:
            return self.quad(subj, pred, obj, graph)
        else:
            return self.triple(subj, pred, obj)

    def lib(self):
        #return WOQLLibrary()
        pass

    def abstract(self, graph, subj):
        """
        Internal Triple-builder functions which allow chaining of partial queries
        """
        if self._triple_builder is None:
            self._create_triple_builder(subj)
        self._triple_builder._add_po("terminus:tag", "terminus:abstract", graph)
        return self

    def node(self, node, node_type):
        if self._triple_builder is None:
            self._create_triple_builder(node, node_type)
        self._triple_builder.subject = node
        return self

    def property(self, pro_id, property_type):
        """
        Add a property at the current class/document

            @param {string} proId - property ID
            @param {string} type  - property type (range)
            @returns WOQLQuery object

            A range could be another class/document or an "xsd":"http://www.w3.org/2001/XMLSchema#" type
            like string|integer|datatime|nonNegativeInteger|positiveInteger etc ..
            (you don't need the prefix xsd for specific a type)
        """
        if self._triple_builder is None:
            self._create_triple_builder()
        if self.adding_class is not None:
            part = self._find_last_subject(self.cursor)
            g = False
            if part is not None:
                gpart = part["woql:graph_filter"] or part["woql:graph"]
            if gpart is not None:
                g = gpart["@value"]
            nq = WOQLSchema().add_property(pro_id, type, g).domain(self.adding_class)
            combine = self.WOQLQuery().json(self.query)
            nwoql = self.WOQLQuery().woql_and(combine, nq)
            nwoql.adding_class = self.adding_class
            return nwoql.updated()
        else:
            pro_id = self._clean_predicate(pro_id)
            self._triple_builder._add_po(pro_id, property_type)
        return self

    def insert(self, insert_id, insert_type, ref_graph):
        insert_type = self._clean_type(insert_type, True)
        if ref_graph is not None:
            return self._add_quad(insert_id, "type", insert_type, ref_graph)
        return self._add_triple(insert_id, "type", insert_type)

    def insert_data(self, data, ref_graph):
        if data.type and data.id:
            data_type = self._clean_type(data.type, True)
            self.insert(data.id, data_type, ref_graph)
            if data.label is not None:
                self.label(data.label)
            if data.description is not None:
                self.description(data.description)
            for k in data:
                if ["id", "label", "type", "description"].indexOf(k) == -1:
                    self.property(k, data[k])
        return self

    def graph(self, g):
        if self._triple_builder is None:
            self._create_triple_builder()
        self._triple_builder.graph(g)
        return self

    def domain(self, d):
        if self._triple_builder is None:
            self._create_triple_builder()
        d = self._cleanClass(d)
        self._triple_builder._add_po("rdfs:domain", d)
        return self

    def label(self, lan, lang):
        if self._triple_builder is None:
            self._create_triple_builder()
        self._triple_builder.label(lan, lang)
        return self

    def description(self, c, lang):
        if self._triple_builder is None:
            self._create_triple_builder()
        self._triple_builder.description(c, lang)
        return self

    def parent(self, *parent_list):
        """Specifies that a new class should have parents class
        param {array} parentList the list of parent class []
        """
        if self._triple_builder is None:
            self._create_triple_builder()
        for i in parent_list:
            pn = self._clean_class(parent_list[i])
            self._triple_builder._add_po("rdfs:subClassOf", pn)
        return self

    def max(self, m):
        if self._triple_builder is not None:
            self._triple_builder.card(m, "max")
        return self

    def cardinality(self, m):
        if self._triple_builder is not None:
            self._triple_builder.card(m, "cardinality")
        return self

    def min(self, m):
        if self._triple_builder is not None:
            self._triple_builder.card(m, "min")
        return self

    def _create_triple_builder(self, node, create_type):
        s = node
        t = create_type
        lastsubj = self.findLastSubject(self.cursor)
        g = False
        if lastsubj is not None:
            gobj = lastsubj["woql:graph_filter"] or lastsubj["woql:graph"]
            if gobj is not None:
                g = gobj["@value"]
            else:
                g = False
            s = lastsubj["woql:subject"]
            if create_type is not None:
                t = create_type
            else:
                t = lastsubj["@type"]
        if self.cursor["@type"] is not None:
            subq = self.WOQLQuery().json(self.cursor)
            if self.cursor["@type"] == "woql:And":
                newq = subq
            else:
                newq = self.WOQLQuery().woql_and(subq)
                nuj = newq.json()
            for k in self.cursor:
                del self.cursor[k]
            for i in nuj:
                self.cursor[i] = nuj[i]
        else:
            self.woql_and()
        self._triple_builder = TripleBuilder(t, self, s, g)


class WOQLSchema:

    """The WOQL Schema Class provides pre-built WOQL queries for schema manipulation
        a) adding and deleting classes and properties
        b) loading datatype libraries
        c) boxing classes
    """

    def __init__(self):
        self.graph = "schema/main"

    def add_class(self, c, graph=None):
        graph = self.graph
        ap = WOQLQuery()
        if c is not None:
            c = ap._clean_class(c, True)
            ap.adding_class = c
            ap.add_quad(c, "rdf:type", "owl:Class", graph)
        return ap

    def insert_class_data(self, data, ref_graph):
        """
            Adds a bunch of class data in one go
        """
        ap = WOQLQuery
        if data.id is not None:
            c = ap._clean_class(data.id, True)
            ap = self.WOQLSchema().add_class(c, ref_graph)
            if data.label is not None:
                ap.label(data.label)
            if data.description is not None:
                ap.description(data.description)
            if data.parent is not None:
                if not isinstance(data.parent, list):
                    data.parent = [data.parent]
                    """ap.parent(...data.parent) TODO"""
            for k in data:
                if ["id", "label", "description", "parent"].indexOf(k) == -1:
                    ap.insert_property_data(k, data[k], ref_graph)
        return ap

    def doctype_data(self, data, ref_graph):
        if data.parent is None:
            data.parent = []
        if not isinstance(data.parent, list):
            data.parent = [data.parent]
        data.parent.append("Document")
        return self.insert_class_data(data, ref_graph)

    def insert_property_data(self, data, ref_graph):
        ap = WOQLQuery
        if data.id is not None:
            c = ap._clean_class(data.id, True)
            ap.add_class(c, ref_graph)
            if data.label is not None:
                ap.label(data.label)
            if data.description is not None:
                ap.description(data.description)
            if data.parent is not None:
                if not isinstance(data.parent, list):
                    data.parent = [data.parent]
                    """ap.parent(...data.parent) TODO"""
            for k in data:
                if ["id", "label", "description", "parent"].indexOf(k) == -1:
                    ap.insert_property_data(k, data[k], ref_graph)
        return ap

    def delete_class(self, c, graph=None):
        if graph is None:
            graph = self.graph
        ap = WOQLQuery
        if c is not None:
            c = ap._clean_class(c, True)
            ap.woql_and(
                WOQLQuery.delete_quad(c, "v:Outgoing", "v:Value", graph),
                WOQLQuery.opt().delete_quad("v:Other", "v:Incoming", c, graph),
            )
            ap.updated()
        return ap

    def add_property(self, p, t, graph=None):
        if graph is None:
            graph = self.graph
        ap = WOQLQuery
        t = ap._clean_type(t, True) if t is not None else "xsd:string"
        if p is not None:
            p = ap._clean_path_predicate(p)
            # TODO: cleaning
            if utils.type_helper._is_data_type(t) is not None:
                ap.woql_and(
                    WOQLQuery.add_quad(p, "rdf:type", "owl:DatatypeProperty", graph),
                    WOQLQuery.add_quad(p, "rdfs:range", t, graph),
                )
            else:
                ap.woql_and(
                    WOQLQuery.add_quad(p, "rdf:type", "owl:ObjectProperty", graph),
                    WOQLQuery.add_quad(p, "rdfs:range", t, graph),
                )
            ap._updated()
        return ap

    def delete_property(self, p, graph=None):
        if graph is None:
            graph = self.graph
        ap = WOQLQuery
        if p is not None:
            p = ap._clean_path_predicate(p)
            # TODO: cleaning
            ap.woql_and(
                WOQLQuery.delete_quad(p, "v:All", "v:Al2", graph),
                WOQLQuery.delete_quad("v:Al3", "v:Al4", p, graph),
            )
            ap.updated()
        return ap

    def box_classes(self, prefix, classes, excepts, graph=None):
        if graph is None:
            graph = self.graph
        prefix = prefix or "scm:"
        subs = []
        for i in classes:
            subs.append(WOQLQuery.sub(classes[i], "v:Cid"))
        nsubs = []
        for i in excepts:
            nsubs.append(WOQLQuery.woql_not().sub(excepts[i], "v:Cid"))
        idgens = [
            WOQLQuery.re("#(.)(.*)", "v:Cid", ["v:AllB", "v:FirstB", "v:RestB"]),
            WOQLQuery.lower("v:FirstB", "v:Lower"),
            WOQLQuery.concat(["v:Lower", "v:RestB"], "v:Propname"),
            WOQLQuery.concat(["Scoped", "v:FirstB", "v:RestB"], "v:Cname"),
            WOQLQuery.idgen(prefix, ["v:Cname"], "v:ClassID"),
            WOQLQuery.idgen(prefix, ["v:Propname"], "v:PropID"),
        ]
        woql_filter = WOQLQuery.woql_and(
            WOQLQuery.quad("v:Cid", "rdf:type", "owl:Class", graph),
            WOQLQuery.woql_not().node("v:Cid").abstract(graph),
            WOQLQuery.woql_and(*idgens),
            WOQLQuery.quad("v:Cid", "label", "v:Label", graph),
            WOQLQuery.concat("Box Class generated for class v:Cid", "v:CDesc", graph),
            WOQLQuery.concat(
                "Box Property generated to link box v:ClassID to class v:Cid",
                "v:PDesc",
                graph,
            ),
        )
        if len(subs):
            if len(subs) == 1:
                woql_filter.woql_and(subs[0])
            else:
                woql_filter.woql_and(WOQLQuery().woql_or(*subs))
        if len(nsubs):
            woql_filter.woql_and(WOQLQuery().woql_and(*nsubs))
        cls = (
            self.WOQLSchema(graph)
            .add_class("v:ClassID")
            .label("v:Label")
            .description("v:CDesc")
        )
        prop = (
            self.WOQLSchema(graph)
            .add_property("v:PropID", "v:Cid")
            .label("v:Label")
            .description("v:PDesc")
            .domain("v:ClassID")
        )
        nq = WOQLQuery.when(woql_filter).woql_and(cls, prop)
        return nq._updated()

    def generate_choice_list(
        self,
        cls=None,
        clslabel=None,
        clsdesc=None,
        choices=None,
        graph=None,
        parent=None,
    ):
        if graph is None:
            graph = self.graph
        clist = []
        if cls.indexOf(":") == -1:
            listid = "_:" + cls
        else:
            listid = "_:" + cls.split(":")[1]
        lastid = listid
        wq = self.WOQLSchema().add_class(cls, graph).label(clslabel)
        if clsdesc is not None:
            wq.description(clsdesc)
        if parent is not None:
            wq.parent(parent)
        confs = [wq]
        for i in choices:
            if choices[i] is None:
                continue
            if type(choices[i]) == list:
                chid = choices[i][0]
                clab = choices[i][1]
                desc = choices[i][2] or False
            else:
                chid = choices[i]
                clab = utils.labelFromURL(chid)
                desc = False
            cq = WOQLQuery.insert(chid, cls, graph).label(clab)
            if desc is not None:
                cq.description(desc)
            confs.append(cq)
            if i < len(choices) == -1:
                nextid = listid + "_" + i
            else:
                nextid = "rdf:nil"
            clist.append(WOQLQuery.add_quad(lastid, "rdf:first", chid, graph))
            clist.append(WOQLQuery.add_quad(lastid, "rdf:rest", nextid, graph))
            lastid = nextid
        oneof = WOQLQuery.woql_and(
            WOQLQuery.add_quad(cls, "owl:oneOf", listid, graph), *clist
        )
        return WOQLQuery.woql_and(*confs, oneof)

    def libs(self, libs, parent, graph, prefix):
        bits = []
        if libs.indexOf("xdd") != -1:
            bits.append(self._load_xdd(graph))
            if libs.indexOf("box") != -1:
                bits.append(self.load_xdd_boxes(parent, graph, prefix))
                bits.append(self.load_xsd_boxes(parent, graph, prefix))
        elif libs.indexOf("box") != -1:
            bits.append(self.load_xsd_boxes(parent, graph, prefix))
        if len(bits) > 1:
            return WOQLQuery.woql_and(*bits)
        return bits[0]

    def load_xdd(self, graph=None):
        if graph is None:
            graph = self.graph
        return WOQLQuery.woql_and(
            # geograhpic datatypes
            self.add_datatype(
                "xdd:coordinate",
                "Coordinate",
                "A latitude / longitude pair making up a coordinate, encoded as: [lat,long]",
                graph,
            ),
            self.add_datatype(
                "xdd:coordinatePolygon",
                "Coordinate Polygon",
                "A JSON list of [[lat,long]] coordinates forming a closed polygon.",
                graph,
            ),
            self.add_datatype(
                "xdd:coordinatePolyline",
                "Coordinate Polyline",
                "A JSON list of [[lat,long]] coordinates.",
                graph,
            ),
            # uncertainty range datatypes
            self.add_datatype(
                "xdd:dateRange",
                "Date Range",
                "A date (YYYY-MM-DD) or an uncertain date range [YYYY-MM-DD1,YYYY-MM-DD2]. "
                + "Enables uncertainty to be encoded directly in the data",
                graph,
            ),
            self.add_datatype(
                "xdd:decimalRange",
                "Decimal Range",
                "Either a decimal value (e.g. 23.34) or an uncertain range of decimal values "
                + "(e.g.[23.4, 4.143]. Enables uncertainty to be encoded directly in the data",
                graph,
            ),
            self.add_datatype(
                "xdd:integerRange",
                "Integer Range",
                "Either an integer (e.g. 30) or an uncertain range of integers [28,30]. "
                + "Enables uncertainty to be encoded directly in the data",
                graph,
            ),
            self.add_datatype(
                "xdd:gYearRange",
                "Year Range",
                "A year (e.g. 1999) or an uncertain range of years: (e.g. [1999,2001])."
                + "Enables uncertainty to be encoded directly in the data",
                graph,
            ),
            # string refinement datatypes
            self.add_datatype("xdd:email", "Email", "A valid email address", graph),
            self.add_datatype(
                "xdd:html", "HTML", "A string with embedded HTML", graph
            ),
            self.add_datatype("xdd:json", "JSON", "A JSON encoded string", graph),
            self.add_datatype("xdd:url", "URL", "A valid http(s) URL", graph),
        )

    def add_datatype(self, d_id, label, descr, graph=None):
        if graph is None:
            graph = self.graph
        # utility function for creating a datatype in woql
        dt = WOQLQuery().insert(d_id, "rdfs:Datatype", graph).label(label)
        if descr is not None:
            dt.description(descr)
        return dt

    def load_xsd_boxes(self, parent, graph, prefix):
        # Loads box classes for all of the useful xsd classes the format is to generate the box classes for xsd:anyGivenType
        # as class(prefix:AnyGivenType) -> property(prefix:anyGivenType) -> datatype(xsd:anyGivenType)
        return WOQLQuery.woql_and(
            self.box_datatype(
                "xsd:anySimpleType",
                "Any Simple Type",
                "Any basic data type such as string or integer. An xsd:anySimpleType value.",
                parent,
                graph,
                prefix,
            ),
            self.box_datatype(
                "xsd:string",
                "String",
                "Any text or sequence of characters",
                parent,
                graph,
                prefix,
            ),
            self.box_datatype(
                "xsd:boolean",
                "Boolean",
                "A true or false value. An xsd:boolean value.",
                parent,
                graph,
                prefix,
            ),
            self.box_datatype(
                "xsd:decimal",
                "Decimal",
                "A decimal number. An xsd:decimal value.",
                parent,
                graph,
                prefix,
            ),
            self.box_datatype(
                "xsd:double",
                "Double",
                "A double-precision decimal number. An xsd:double value.",
                parent,
                graph,
                prefix,
            ),
            self.box_datatype(
                "xsd:float",
                "Float",
                "A floating-point number. An xsd:float value.",
                parent,
                graph,
                prefix,
            ),
            self.box_datatype(
                "xsd:time",
                "Time",
                "A time. An xsd:time value. hh:mm:ss.ssss",
                parent,
                graph,
                prefix,
            ),
            self.box_datatype(
                "xsd:date",
                "Date",
                "A date. An xsd:date value. YYYY-MM-DD",
                parent,
                graph,
                prefix,
            ),
            self.box_datatype(
                "xsd:dateTime",
                "Date Time",
                "A date and time. An xsd:dateTime value.",
                parent,
                graph,
                prefix,
            ),
            self.box_datatype(
                "xsd:dateTimeStamp",
                "Date-Time Stamp",
                "An xsd:dateTimeStamp value.",
                parent,
                graph,
                prefix,
            ),
            self.box_datatype(
                "xsd:gYear",
                "Year",
                " A particular 4 digit year YYYY - negative years are BCE.",
                parent,
                graph,
                prefix,
            ),
            self.box_datatype(
                "xsd:gMonth",
                "Month",
                "A particular month. An xsd:gMonth value. --MM",
                parent,
                graph,
                prefix,
            ),
            self.box_datatype(
                "xsd:gDay",
                "Day",
                "A particular day. An xsd:gDay value. ---DD",
                parent,
                graph,
                prefix,
            ),
            self.box_datatype(
                "xsd:gYearMonth",
                "Year / Month",
                "A year and a month. An xsd:gYearMonth value.",
                parent,
                graph,
                prefix,
            ),
            self.box_datatype(
                "xsd:gMonthDay",
                "Month / Day",
                "A month and a day. An xsd:gMonthDay value.",
                parent,
                graph,
                prefix,
            ),
            self.box_datatype(
                "xsd:duration",
                "Duration",
                "A period of time. An xsd:duration value.",
                parent,
                graph,
                prefix,
            ),
            self.box_datatype(
                "xsd:yearMonthDuration",
                "Year / Month Duration",
                "A duration measured in years and months. An xsd:yearMonthDuration value.",
                parent,
                graph,
                prefix,
            ),
            self.box_datatype(
                "xsd:dayTimeDuration",
                "Day / Time Duration",
                "A duration measured in days and time. An xsd:dayTimeDuration value.",
                parent,
                graph,
                prefix,
            ),
            self.box_datatype(
                "xsd:byte", "Byte", "An xsd:byte value.", parent, graph, prefix
            ),
            self.box_datatype(
                "xsd:short", "Short", "An xsd:short value.", parent, graph, prefix
            ),
            self.box_datatype(
                "xsd:integer",
                "Integer",
                "A simple number. An xsd:integer value.",
                parent,
                graph,
                prefix,
            ),
            self.box_datatype(
                "xsd:long", "Long", "An xsd:long value.", parent, graph, prefix
            ),
            self.box_datatype(
                "xsd:unsignedByte",
                "Unsigned Byte",
                "An xsd:unsignedByte value.",
                parent,
                graph,
                prefix,
            ),
            self.box_datatype(
                "xsd:unsignedInt",
                "Unsigned Integer",
                "An xsd:unsignedInt value.",
                parent,
                graph,
                prefix,
            ),
            self.box_datatype(
                "xsd:unsignedLong",
                "Unsigned Long Integer",
                "An xsd:unsignedLong value.",
                parent,
                graph,
                prefix,
            ),
            self.box_datatype(
                "xsd:positiveInteger",
                "Positive Integer",
                "A simple number greater than 0. An xsd:positiveInteger value.",
                parent,
                graph,
                prefix,
            ),
            self.box_datatype(
                "xsd:nonNegativeInteger",
                "Non-Negative Integer",
                "A simple number that can't be less than 0. An xsd:nonNegativeInteger value.",
                parent,
                graph,
                prefix,
            ),
            self.box_datatype(
                "xsd:negativeInteger",
                "Negative Integer",
                "A negative integer. An xsd:negativeInteger value.",
                parent,
                graph,
                prefix,
            ),
            self.box_datatype(
                "xsd:nonPositiveInteger",
                "Non-Positive Integer",
                "A number less than or equal to zero. An xsd:nonPositiveInteger value.",
                parent,
                graph,
                prefix,
            ),
            self.box_datatype(
                "xsd:base64Binary",
                "Base 64 Binary",
                "An xsd:base64Binary value.",
                parent,
                graph,
                prefix,
            ),
            self.box_datatype(
                "xsd:anyURI",
                "Any URI",
                "Any URl. An xsd:anyURI value.",
                parent,
                graph,
                prefix,
            ),
            self.box_datatype(
                "xsd:language",
                "Language",
                "A natural language identifier as defined by by [RFC 3066] . An xsd:language value.",
                parent,
                graph,
                prefix,
            ),
            self.box_datatype(
                "xsd:normalizedString",
                "Normalized String",
                "An xsd:normalizedString value.",
                parent,
                graph,
                prefix,
            ),
            self.box_datatype(
                "xsd:token", "Token", "An xsd:token value.", parent, graph, prefix
            ),
            self.box_datatype(
                "xsd:NMTOKEN", "NMTOKEN", "An xsd:NMTOKEN value.", parent, graph, prefix
            ),
            self.box_datatype(
                "xsd:Name", "Name", "An xsd:Name value.", parent, graph, prefix
            ),
            self.box_datatype(
                "xsd:NCName", "NCName", "An xsd:NCName value.", parent, graph, prefix
            ),
            self.box_datatype(
                "xsd:NOTATION",
                "NOTATION",
                "An xsd:NOTATION value.",
                parent,
                graph,
                prefix,
            ),
            self.box_datatype(
                "xsd:QName", "QName", "An xsd:QName value.", parent, graph, prefix
            ),
            self.box_datatype(
                "xsd:ID", "ID", "An xsd:ID value.", parent, graph, prefix
            ),
            self.box_datatype(
                "xsd:IDREF", "IDREF", "An xsd:IDREF value.", parent, graph, prefix
            ),
            self.box_datatype(
                "xsd:ENTITY", "ENTITY", "An xsd:ENTITY value.", parent, graph, prefix
            ),
        )

    def load_xdd_boxes(self, parent, graph, prefix):
        # Generates a query to create box classes for all of the xdd datatypes. the format is to generate the box classes for xdd:anyGivenType
        # as class(prefix:AnyGivenType) -> property(prefix:anyGivenType) -> datatype(xdd:anyGivenType)
        return WOQLQuery.woql_and(
            self.box_datatype(
                "xdd:coordinate",
                "Coordinate",
                "A particular location on the surface of the earth, defined by latitude and longitude . An xdd:coordinate value.",
                parent,
                graph,
                prefix,
            ),
            self.box_datatype(
                "xdd:coordinatePolygon",
                "Geographic Area",
                "A shape on a map which defines an area. within the defined set of coordinates   An xdd:coordinatePolygon value.",
                parent,
                graph,
                prefix,
            ),
            self.box_datatype(
                "xdd:coordinatePolyline",
                "Coordinate Path",
                "A set of coordinates forming a line on a map, representing a route. An xdd:coordinatePolyline value.",
                parent,
                graph,
                prefix,
            ),
            self.box_datatype("xdd:url", "URL", "A valid url.", parent, graph, prefix),
            self.box_datatype(
                "xdd:email", "Email", "A valid email address.", parent, graph, prefix
            ),
            self.box_datatype(
                "xdd:html", "HTML", "A safe HTML string", parent, graph, prefix
            ),
            self.box_datatype("xdd:json", "JSON", "A JSON Encoded String"),
            self.box_datatype(
                "xdd:gYearRange",
                "Year",
                "A 4-digit year, YYYY, or if uncertain, a range of years. An xdd:gYearRange value.",
                parent,
                graph,
                prefix,
            ),
            self.box_datatype(
                "xdd:integerRange",
                "Integer",
                "A simple number or range of numbers. An xdd:integerRange value.",
                parent,
                graph,
                prefix,
            ),
            self.box_datatype(
                "xdd:decimalRange",
                "Decimal Number",
                "A decimal value or, if uncertain, a range of decimal values. An xdd:decimalRange value.",
                parent,
                graph,
                prefix,
            ),
            self.box_datatype(
                "xdd:dateRange",
                "Date Range",
                "A date or a range of dates YYYY-MM-DD",
                parent,
                graph,
                prefix,
            ),
        )

    def box_datatype(
        self,
        datatype=None,
        label=None,
        descr=None,
        parent=None,
        graph=None,
        prefix=None,
    ):
        # utility function for boxing a datatype in woql
        # format is (predicate) prefix:datatype (domain) prefix:Datatype (range) xsd:datatype
        if graph is None:
            graph = self.graph
        prefix = prefix or "scm:"
        ext = datatype.split(":")[1]
        box_class_id = prefix + ext.charAt(0).toUpperCase() + ext.slice(1)
        box_prop_id = prefix + ext.charAt(0).toLowerCase() + ext.slice(1)
        box_class = self._add_class(box_class_id, graph).label(label)
        box_class.description("Boxed Class for " + datatype)
        if parent is not None:
            box_class.parent(parent)
        box_prop = (
            self._add_property(box_prop_id, datatype, graph)
            .label(label)
            .domain(box_class_id)
        )
        if descr is not None:
            box_prop.description(descr)
        return WOQLQuery.woql_and(box_class, box_prop)
