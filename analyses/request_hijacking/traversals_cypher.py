# -*- coding: utf-8 -*-

"""
	Copyright (C) 2020  Soheil Khodayari, CISPA
	This program is free software: you can redistribute it and/or modify
	it under the terms of the GNU Affero General Public License as published by
	the Free Software Foundation, either version 3 of the License, or
	(at your option) any later version.
	This program is distributed in the hope that it will be useful,
	but WITHOUT ANY WARRANTY; without even the implied warranty of
	MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
	GNU Affero General Public License for more details.
	You should have received a copy of the GNU Affero General Public License
	along with this program.  If not, see <http://www.gnu.org/licenses/>.


	Description:
	------------
	Cypher traversals for detecting request hijacking vulnerabilities

	Usage:
	-----------
	> import analyses.request_hijacking.traversals_cypher as request_hijacking_py_traversals

"""

import subprocess
import hashlib
import urllib.parse
import os
import time
import re
import sys
import jsbeautifier
import json

import constants as constantsModule
import utils.utility as utilityModule
import hpg_neo4j.db_utility as DU
import hpg_neo4j.query_utility as QU
import analyses.general.data_flow as DF
import analyses.request_hijacking.semantic_types as SemTypeDefinitions

# import analyses.request_hijacking.semantic_types as SemanticTypesModule

from utils.logging import logger as LOGGER
from neo4j import GraphDatabase
from datetime import datetime


# ----------------------------------------------------------------------- #
#				Globals
# ----------------------------------------------------------------------- #


DEBUG = False


# ----------------------------------------------------------------------- #
#				Utility Functions
# ----------------------------------------------------------------------- #


def _unquote_url(url):
	
	"""
	@param {string} url
	@return {string} decoded url
	"""
	out = urllib.parse.unquote(url)
	out = out.replace('&amp;', '&')

	return out

def _get_all_occurences(needle, haystack):
	
	"""
	@param {string} needle
	@param {string haystack
	@description finds all occurences of needle in haystack
	@return {array} a list of start index occurences of needle in haystack
	"""
	out = [m.start() for m in re.finditer(needle, haystack)]
	return out


def _get_current_timestamp():
	
	"""
	@return {string} current date and time string
	"""
	now = datetime.now()
	dt_string = now.strftime("%d/%m/%Y %H:%M:%S")
	return dt_string

def _get_unique_list(lst):
	
	"""
	@param {list} lst
	@return remove duplicates from list and return the resulting array
	"""
	return list(set(lst))


def _get_orderd_unique_list(lst):
	
	"""
	@param {list} lst
	@return remove duplicates from list and return the resulting array maintaining the original list order
	"""
	final_list = [] 
	for item in lst: 
		if item not in final_list: 
			final_list.append(item) 
	return final_list 

def _get_line_of_location(esprima_location_str):
	
	"""
	@param esprima_location_str
	@return start line numnber of esprima location object
	"""
	start_index = esprima_location_str.index('line:') + len('line:')
	end_index = esprima_location_str.index(',')
	out = esprima_location_str[start_index:end_index]
	return out

def _get_location_part(nid_string):
	
	"""
	@param {string} nid_string: string containing node id and location
	@return {string} node id string
	"""
	start_index = nid_string.index('__Loc=') + len('__Loc=')
	return nid_string[start_index:]

def _get_node_id_part(nid_string):
	
	"""
	@param {string} nid_string: string containing node id and location
	@return {string} location string
	"""
	start_index = nid_string.find('__nid=')
	if start_index != -1:
		start_index = start_index + len('__nid=')
	else:
		start_index = 0 # handle the case where function name is not stored at the begining

	end_index = nid_string.index('__Loc=')
	return nid_string[start_index:end_index]


def _get_function_name_part(nid_string):
	
	"""
	@param {string} nid_string: string containing node id and location
	@return {string} function_name string
	"""
	end_index = nid_string.index('__nid=')
	return nid_string[:end_index]



def _get_value_of_identifer_or_literal(node):
	"""
	@param {PGNode} node
	@return {list} returns the pair of the value of a node and the node type  (identifer or literal)
	"""
	if node['Type'] == 'Identifier':
		return [node['Code'], node['Type']]
	elif node['Type'] == 'Literal':
		value = node['Value']
		raw = node['Raw']
		if value == '{}' and (raw.strip('\'').strip("\"").strip() != value):
			return [node['Raw'], node['Type']]
		else:
			return [node['Value'], node['Type']]

	return ['', '']



# ----------------------------------------------------------------------- #
#		Semantic Type Association to Program Slices 
# ----------------------------------------------------------------------- #

def _get_semantic_types(program_slices, num_slices):
	
	"""
	@param {list} program_slices: slices of JS program
	@param {int} num_slices: length of program_slices list
	@return {list} the semantic types associated with the given program slices.
	"""


	semantic_type = SemTypeDefinitions.NON_REACHABLE
	semantic_types = []


	# sources
	WEB_STORAGE_STRINGS = [
		'localStorage',
		'sessionStorage'
	]

	WIN_LOC_STRINGS = [
		'window.location',
		'win.location',
		'w.location',
		'location.href',
		'location.hash',
		'loc.href',
		'loc.hash',
		'History.getBookmarkedState',
	]

	WIN_NAME_STRINGS = [
		'window.name',
		'win.name'
	]

	DOM_READ_STRINGS = [
		'document.getElement',
		'document.querySelector',
		'doc.getElement',
		'doc.querySelector',
		'.getElementBy',
		'.getElementsBy',
		'.querySelector',
		'$(',
		'jQuery(',
		'.attr(',
		'.getAttribute(',
		'.readAttribute('
	]

	DOM_READ_COOKIE_STRINGS = [
		'document.cookie',
		'doc.cookie',
	]

	PM_STRINGS = [
		'event.data', 
		'evt.data'
	]

	DOC_REF_STRINGS = [
		'document.referrer',
		'doc.referrer',
		'd.referrer',
	]

	# push subscription
	PUSH_SUBSCRIPTION_API = [
		'pushManager.getSubscription', 
		'pushManager.subscribe',
		'pushManager',
	]

	for i in range(num_slices):
		program_slice = program_slices[i]
		code = program_slice[0]
		idents = program_slice[2]

		for item in WIN_LOC_STRINGS:
			if item in code:
				semantic_type = SemTypeDefinitions.RD_WIN_LOC
				semantic_types.append(semantic_type)
				

		for item in WIN_NAME_STRINGS:
			if item in code:
				semantic_type = SemTypeDefinitions.RD_WIN_NAME
				semantic_types.append(semantic_type)
				

		for item in DOC_REF_STRINGS:
			if item in code:
				semantic_type = SemTypeDefinitions.RD_DOC_REF
				semantic_types.append(semantic_type)



		for item in PM_STRINGS:
			if item in code:
				semantic_type = SemTypeDefinitions.RD_PM
				semantic_types.append(semantic_type)
				


		for item in DOM_READ_STRINGS:
			if item in code:
				semantic_type = SemTypeDefinitions.RD_DOM_TREE
				semantic_types.append(semantic_type)
				

		for item in WEB_STORAGE_STRINGS:
			if item in code:
				semantic_type = SemTypeDefinitions.RD_WEB_STORAGE
				semantic_types.append(semantic_type)
				

		for item in DOM_READ_COOKIE_STRINGS:
			if item in code:
				semantic_type = SemTypeDefinitions.RD_COOKIE
				semantic_types.append(semantic_type)
				

		for item in PUSH_SUBSCRIPTION_API:
			if item in code:
				semantic_type = SemTypeDefinitions.REQ_PUSH_SUB
				semantic_types.append(semantic_type)


		for identifier in idents:

			for item in WIN_LOC_STRINGS:
				if item in identifier:
					semantic_type = SemTypeDefinitions.RD_WIN_LOC
					semantic_types.append(semantic_type)
					

			for item in WIN_NAME_STRINGS:
				if item in identifier:
					semantic_type = SemTypeDefinitions.RD_WIN_NAME
					semantic_types.append(semantic_type)
					

			for item in DOC_REF_STRINGS:
				if item in identifier:
					semantic_type = SemTypeDefinitions.RD_DOC_REF
					semantic_types.append(semantic_type)



			for item in PM_STRINGS:
				if item in identifier:
					semantic_type = SemTypeDefinitions.RD_PM
					semantic_types.append(semantic_type)
					


			for item in DOM_READ_STRINGS:
				if item in identifier:
					semantic_type = SemTypeDefinitions.RD_DOM_TREE
					semantic_types.append(semantic_type)
					

			for item in WEB_STORAGE_STRINGS:
				if item in identifier:
					semantic_type = SemTypeDefinitions.RD_WEB_STORAGE
					semantic_types.append(semantic_type)
					

			for item in DOM_READ_COOKIE_STRINGS:
				if item in identifier:
					semantic_type = SemTypeDefinitions.RD_COOKIE
					semantic_types.append(semantic_type)
		
			for item in PUSH_SUBSCRIPTION_API:
				if item in identifier:
					semantic_type = SemTypeDefinitions.REQ_PUSH_SUB
					semantic_types.append(semantic_type)


	if len(semantic_types):
		return list(set(semantic_types))

	return [SemTypeDefinitions.NON_REACHABLE]


def _get_semantic_type_set(semantic_type_list):
	
	"""
	@param {list} semantic_type_list: list of types that may include duplicate semantic types
	@return {list} a unique semantic type list
	"""

	semantic_type_list = _get_unique_list(semantic_type_list)
	if len(semantic_type_list) > 1:
		if SemTypeDefinitions.NON_REACHABLE in semantic_type_list:
			semantic_type_list.remove(SemTypeDefinitions.NON_REACHABLE)
		return semantic_type_list	

	elif len(semantic_type_list) == 1:
		return semantic_type_list

	else:
		return [SemTypeDefinitions.NON_REACHABLE]


# ----------------------------------------------------------------------- #
#		Cypher queries for request sending sinks 
# ----------------------------------------------------------------------- #


def getWindowOpenCallExpressions(tx):
	
	"""
	@param {pointer} tx
	@return bolt result (t, n, a): where t= top level exp statement, n = callExpression, a=URL argument of the xhr.open() function
	"""

	query="""
	MATCH (t {Type: 'ExpressionStatement'})-[:AST_parentOf {RelationType: 'expression'}]->(n {Type: 'CallExpression'})-[:AST_parentOf {RelationType: 'callee'}]-> (n1 {Type: 'MemberExpression'})-[:AST_parentOf {RelationType: 'property'}]->(req {Type: 'Identifier', Code: 'open'}),
	(n1)-[:AST_parentOf {RelationType: 'object'}]->(callee),
	(n)-[:AST_parentOf {RelationType: 'arguments', Arguments: '{\"arg\":0}'}]->(a)
	WHERE callee.Code= 'window'
	RETURN t, n, a
	"""
	results = tx.run(query)
	return results


def getXhrOpenCallExpressions(tx):
	
	"""
	@param {pointer} tx
	@return bolt result (t, n, a): where t= top level exp statement, n = callExpression, a=URL argument of the xhr.open() function
	"""

	query="""
	MATCH (t {Type: 'ExpressionStatement'})-[:AST_parentOf {RelationType: 'expression'}]->(n {Type: 'CallExpression'})-[:AST_parentOf {RelationType: 'callee'}]-> (n1 {Type: 'MemberExpression'})-[:AST_parentOf {RelationType: 'property'}]->(req {Type: 'Identifier', Code: 'open'}),
	(n1)-[:AST_parentOf {RelationType: 'object'}]->(callee),
	(n)-[:AST_parentOf {RelationType: 'arguments', Arguments: '{\"arg\":1}'}]->(a)
	WHERE callee.Code <> 'window'
	RETURN t, n, a
	"""
	results = tx.run(query)
	return results



def getFetchCallExpressions(tx):
	
	"""
	@param {pointer} tx
	@return bolt result (t, n, a): where t= top level exp statement, n = callExpression, a=URL argument of the fetch() function
	"""

	query="""
	MATCH (t {Type: 'ExpressionStatement'})-[:AST_parentOf {RelationType: 'expression'}]->(n {Type: 'CallExpression'})-[:AST_parentOf {RelationType: 'callee'}]-> (req {Type: 'Identifier', Code: 'fetch'}), 
	(n)-[:AST_parentOf {RelationType: 'arguments', Arguments: '{\"arg\":0}'}]->(a)
	RETURN t, n, a
	"""
	results = tx.run(query)
	return results



def getAjaxCallExpressions(tx):
	
	"""
	@param {pointer} tx
	@return bolt result (t, n, a): where t= top level exp statement, n = callExpression, a=URL argument of the $.ajax() function
	"""

	# argument a can be ObjectExpression, Identifier, or MemberExpression
	# variable relation length will capture function chains, e.g., $.ajax({}).done().success().failure() etc.
	query="""
	MATCH (t {Type: 'ExpressionStatement'})-[:AST_parentOf*1..10]->(n {Type: 'CallExpression'})-[:AST_parentOf {RelationType: 'callee'}]-> (n1 {Type: 'MemberExpression'})-[:AST_parentOf {RelationType: 'property'}]->(req {Type: 'Identifier', Code: 'ajax'}),
	(n1)-[:AST_parentOf {RelationType: 'object'}]->(n2 {Type: 'Identifier' }),
	(n)-[:AST_parentOf {RelationType: 'arguments', Arguments: '{\"arg\":0}'}]->(a)
	OPTIONAL MATCH (a)-[:AST_parentOf {RelationType: 'properties'}]->(n4 {Type: 'Property'})-[:AST_parentOf {RelationType: 'key'}]->(n5 {Type: 'Identifier', Code: 'url'}),
	(n4)-[:AST_parentOf {RelationType: 'value'}]->(aa)
	RETURN t, n, a, aa
	"""
	results = tx.run(query)

	return results


def xhrPostCallExpressions(tx):
	"""
	@param {pointer} tx
	@return bolt result (t, n, a): where t= top level exp statement, n = callExpression, a=options argument of the xhrPost(endpoint, options) function

	@Note: xhrPost is used e.g., in tinytinyrss
	"""
	query="""
	MATCH (t {Type: 'ExpressionStatement'})-[:AST_parentOf {RelationType: 'expression'}]->(n {Type: 'CallExpression'})-[:AST_parentOf {RelationType: 'callee'}]-> (req {Type: 'Identifier', Code: 'xhrPost'}), 
	(n)-[:AST_parentOf {RelationType: 'arguments', Arguments: '{\"arg\":1}'}]->(a)
	RETURN t, n, a
	"""
	results = tx.run(query)
	return results




def getAsyncRequestCallExpressions(tx):
	
	"""
	@param {pointer} tx
	@return bolt result (t, n, a): where t= top level exp statement, n = callExpression, a=URL argument of the asyncRequest() function
	"""

	query="""
	MATCH (t)-[:AST_parentOf]->(n {Type: 'CallExpression'})-[:AST_parentOf {RelationType: 'callee'}]->(n1 {Type: 'MemberExpression'})-[:AST_parentOf {RelationType: 'property'}]->(req {Type: 'Identifier', Code: 'asyncRequest'}),
	(n)-[:AST_parentOf {RelationType: 'arguments', Arguments: '{\"arg\":1}'}]->(a)
	OPTIONAL MATCH (tt)-[:AST_parentOf]->(t) WHERE tt.Type='VariableDeclaration' OR tt.Type='ExpressionStatement'
	RETURN  tt, t, n, a
	"""
	results = tx.run(query)
	return results



def getSetFormCallExpressions(tx):

	"""
	@param {pointer} tx
	@return 
	"""

	query = """
	MATCH (call_expression {Type: 'CallExpression'})-[:AST_parentOf {RelationType: 'callee'}]-(member_expression {Type: 'MemberExpression'})-[:AST_parentOf {RelationType: 'property'}]->(set_form {Code:'setForm', Type: 'Identifier'}),
	(call_expression)-[:AST_parentOf {RelationType: 'arguments', Arguments: '{\"arg\":0}'}]->(arg), (t)-[:AST_parentOf]->(call_expression)
	OPTIONAL MATCH (tt)-[:AST_parentOf]->(t) WHERE tt.Type='VariableDeclaration' OR tt.Type='ExpressionStatement'
	RETURN tt, t, call_expression as n, arg as a
	"""
	results = tx.run(query)
	return results


def getPageSpeedExpressions(tx):
	"""
	@param {pointer} tx
	@return bolt result (t, n, a): where t= top level exp statement, n = callExpression, a=URL argument of the asyncRequest() function
	"""

	query = """
	MATCH (t {Type: 'ExpressionStatement'})-[:AST_parentOf {RelationType: 'expression'}]->(call_expr {Type: 'CallExpression'})-[:AST_parentOf {RelationType: 'callee'}]->(member_expr {Type: 'MemberExpression'})-[:AST_parentOf {RelationType: 'property'}]->(run {Type: 'Identifier', Code: 'Run'}),
	(member_expr)-[:AST_parentOf {RelationType: 'object'}]->(inner_member_expression {Type: 'MemberExpression'})-[:AST_parentOf {RelationType: 'property'}]->(ci {Type: 'Identifier', Code: 'CriticalImages'}), (inner_member_expression)-[:AST_parentOf {RelationType: 'object'}]->(ps {Type: 'Identifier', Code: 'pagespeed'}),
	(call_expr)-[:AST_parentOf {RelationType: 'arguments', Arguments: '{\"arg\":1}'}]->(a)
	RETURN t, call_expr AS n, a
	"""
	results = tx.run(query)
	return results


def getAjaxSettingObjectExpressions(tx):
	"""
	@param {pointer} tx
	@return bolt result (t, n, a): where t= top level exp statement, n = ObjectExpression, a=URL argument of the ajaxSettings{} 
	"""

	query = """
	MATCH (t {Type: 'ExpressionStatement'})-[:AST_parentOf*1..5]->(call_expr {Type: 'CallExpression'})-[:AST_parentOf {RelationType: 'arguments'}]->(obj_expr {Type: 'ObjectExpression'})-[:AST_parentOf {RelationType: 'properties'}]->(ajaxSettingsProperty {Type: 'Property'})-[:AST_parentOf {RelationType: 'key'}]->(ajaxSettingsIdentifier {Type: 'Identifier', Code: 'ajaxSettings'}),
	(ajaxSettingsProperty)-[:AST_parentOf {RelationType: 'value'}]->(ajaxSettingsObjExpr {Type: 'ObjectExpression'})-[:AST_parentOf {RelationType: 'properties'}]->(urlProperty {Type: 'Property'})-[:AST_parentOf {RelationType: 'key'}]->(url {Type: 'Identifier', Code: 'url'}),
	(urlProperty)-[:AST_parentOf {RelationType: 'value'}]->(a)
	RETURN t, ajaxSettingsProperty AS n, a
	"""
	results = tx.run(query)
	return results



def getHttpRequestCallExpressionUrlArgument(tx, node, function_type):
	
	"""
	@param {pointer} tx
	@param {node} node: 'CallExpression' node 
	@param {string} function_type: options are ajax, fetch, open
	@return bolt result (n, a): where t= top level exp statement, n = callExpression, a=URL argument of the request-sending function
	"""

	nodeId = node['Id']
	out = []
	query = ''
	if function_type == 'fetch':
		query="""
		MATCH (t {Type: 'ExpressionStatement'})-[:AST_parentOf {RelationType: 'expression'}]->(n { Id: '%s', Type: 'CallExpression'})-[:AST_parentOf {RelationType: 'callee'}]-> (req {Type: 'Identifier', Code: 'fetch'}), 
		(n)-[:AST_parentOf {RelationType: 'arguments', Arguments: '{\"arg\":0}'}]->(a)
		RETURN t, n, a
		"""%(nodeId)
	elif function_type == 'open':
		query="""
		MATCH (t {Type: 'ExpressionStatement'})-[:AST_parentOf {RelationType: 'expression'}]->(n { Id: '%s', Type: 'CallExpression'})-[:AST_parentOf {RelationType: 'callee'}]-> (n1 {Type: 'MemberExpression'})-[:AST_parentOf {RelationType: 'property'}]->(req {Type: 'Identifier', Code: 'open'}), 
		(n)-[:AST_parentOf {RelationType: 'arguments', Arguments: '{\"arg\":1}'}]->(a)
		RETURN t, n, a
		"""%(nodeId)
	elif function_type == 'ajax':
		query="""
		MATCH (t {Type: 'ExpressionStatement'})-[:AST_parentOf {RelationType: 'expression'}]->(n { Id: '%s', Type: 'CallExpression'})-[:AST_parentOf {RelationType: 'callee'}]-> (n1 {Type: 'MemberExpression'})-[:AST_parentOf {RelationType: 'property'}]->(req {Type: 'Identifier', Code: 'ajax'}),
		(n1)-[:AST_parentOf {RelationType: 'object'}]->(n2 {Type: 'Identifier', Code: '$'}),
		(n)-[:AST_parentOf {RelationType: 'arguments', Arguments: '{\"arg\":0}'}]->(n3 {Type: 'ObjectExpression'})-[:AST_parentOf {RelationType: 'properties'}]->(n4 {Type: 'Property'})-[:AST_parentOf {RelationType: 'key'}]->(n5 {Type: 'Identifier', Code: 'url'}),
		(n4)-[:AST_parentOf {RelationType: 'value'}]->(a)
		RETURN t, n, a
		"""%(nodeId)
	elif function_type == 'asyncRequest':
		query="""
		MATCH (t {Type: 'ExpressionStatement'})-[:AST_parentOf {RelationType: 'expression'}]->(n { Id: '%s', Type: 'CallExpression'})-[:AST_parentOf {RelationType: 'callee'}]->(n1 {Type: 'MemberExpression'})-[:AST_parentOf {RelationType: 'property'}]->(req {Type: 'Identifier', Code: 'asyncRequest'}),
		(n)-[:AST_parentOf {RelationType: 'arguments', Arguments: '{\"arg\":1}'}]->(a)
		RETURN t, n, a
		"""%(nodeId)
	if len(query):
		out = tx.run(query)
	return out



def getIdentifierLocalAndGlobalValues(tx, varname):
	"""
	gets the expected value(s) of an identifier from local and global scopes
	@param tx {pointer} neo4j transaction pointer
	@param {string} varname: identifier to resolve
	@return {list} list of back traces for the given identifer
	"""

	stack = []
	query = """
		MATCH (n { Type:'Identifier', Code: '%s'})<-[:AST_parentOf {RelationType: 'id'}]-(vdtor {Type: 'VariableDeclarator'})<-[:AST_parentOf {RelationType:'declarations'}]-(vdtion),
		(vdtor)-[:AST_parentOf {RelationType: 'init'}]->(value)
		RETURN vdtion, value
	"""%(varname)
	results = tx.run(query)

	for pair in results:
		# must at most one pair exist, otherwise, there are 2 or more potential values defined for a single variable at different scopes!
		top_variable_declaration = pair['vdtion']
		init_value = pair['value']
		recurse = False
		if init_value['Type'] == 'Literal':
			expression = '%s %s = \"%s\"'%(top_variable_declaration['Kind'], varname, init_value['Value'])
		elif init_value['Type'] == 'Identifier':
			expression = '%s %s = %s'%(top_variable_declaration['Kind'], varname, init_value['Code'])
			recurse = True
		elif init_value['Type'] == 'FunctionExpression':
			expression = '%s %s = %s'%(top_variable_declaration['Kind'], varname, 'function(){ ... }')
		else:
			init_tree = QU.getChildsOf(tx, init_value)
			ce = QU.get_code_expression(init_tree)
			expression = '%s %s = %s'%(top_variable_declaration['Kind'], varname, ce[0]) 	
			
		knowledge = {varname: {'top': top_variable_declaration, 'init': init_value, 'expression': expression}} 
		stack.append(knowledge)

		if recurse:
			new_varname = init_value['Code']
			child_stack = getIdentifierLocalAndGlobalValues(tx, new_varname)
			stack.extend(child_stack)



	return stack




# ----------------------------------------------------------------------- #
#			Main: Taint Analysis
# ----------------------------------------------------------------------- #


def run_traversals(tx, webpage_url, webpage_directory, webpage_directory_hash='xxx', named_properties=[]):
	"""
	@param {string} webpage_url
	@param {string} webpage_directory
	@param {list} named_properties: `id` and `name` attributes in HTML that can be accessed through the `document` API
	@return {list} a list of candidate requests for hjacking
	"""


	sinks_file = os.path.join(webpage_directory, "sinks.out.json")
	if not os.path.exists(sinks_file):
		LOGGER.error('[TR] sinks.out file does not exist in %s'%webpage_directory)
		return -1


	fd = open(sinks_file, 'r')
	sinks_json = json.load(fd)
	fd.close()
	sinks_list = sinks_json['sinks']

	storage = {}


	for sink_node in sinks_list:

		# if DEBUG:
		# 	debug_node_id = '622'
		# 	if sink_node["id"] != debug_node_id: continue 

		taintable_sink_identifiers = []

		sink_identifiers_dict = sink_node["sink_identifiers"]
		sink_taintable_semantic_types = []
		sink_taint_possiblity_vector = sink_node["taint_possibility"]
		
		for semantic_type in sink_taint_possiblity_vector:
			if sink_taint_possiblity_vector[semantic_type] == True:
				sink_taintable_semantic_types.append(semantic_type)
				taintable_sink_identifiers.extend(sink_identifiers_dict[semantic_type])


		sink_id = str(sink_node["id"])
		sink_location = str(sink_node["location"])
		sink_type = sink_node["sink_type"]
		sink_cfg_node = QU.get_ast_topmost(tx, {"Id": "%s"%sink_id})

		# if DEBUG: 
		# 	print(QU.get_code_expression(QU.getChildsOf(tx, sink_cfg_node)))
		# 	print('sink_cfg_node', sink_cfg_node['Id'])
		

		nid = sink_type + '__nid=' + sink_id + '__Loc=' + sink_location

		sink_node["taintable_semantic_types"] = sink_taintable_semantic_types
		sink_node["cfg_node_id"] = sink_cfg_node["Id"]

		storage[nid] = {
			"sink": sink_node,
			"variables": {}
		}

		

		for varname in taintable_sink_identifiers:
			slice_values = DF._get_varname_value_from_context(tx, varname, sink_cfg_node)

			if DEBUG: print(varname, slice_values)

			semantic_types = _get_semantic_types(slice_values,len(slice_values))
			storage[nid]["variables"][varname]= {
				"slices": slice_values,
				"semantic_types": semantic_types
			}

			lst = storage[nid]["sink"]["taintable_semantic_types"]
			lst.extend(semantic_types)
			storage[nid]["sink"]["taintable_semantic_types"] = lst



	
	print_buffer = []
	json_buffer =  {} # TODO: store data in JSON format too: `sinks.flows.out.json`

	timestamp = _get_current_timestamp()
	sep = utilityModule.get_output_header_sep()
	sep_sub = utilityModule.get_output_subheader_sep()
	print_buffer.append(sep)
	print_buffer.append('[timestamp] generated on %s\n'%timestamp)
	print_buffer.append(sep+'\n')
	print_buffer.append('[*] webpage URL: %s\n\n'%webpage_url)
	print_buffer.append(sep_sub+'\n')

	json_buffer["url"] = webpage_url
	json_buffer["flows"] = []
	for sink_nid in storage:

		sink_node = storage[sink_nid]["sink"]

		print_buffer.append('[*] webpage: %s\n'%webpage_directory_hash)
		script_name = sink_node["script"].split('/')[-1]
		print_buffer.append('[*] script: %s\n'%script_name)
		semantic_types_for_sink = _get_unique_list(sink_node["taintable_semantic_types"])
		print_buffer.append('[*] semantic_types: {0}\n'.format(semantic_types_for_sink))
		print_buffer.append('[*] node_id: %s\n'%str(sink_node["id"]))
		print_buffer.append('[*] cfg_node_id: %s\n'%str(sink_node["cfg_node_id"]))
		print_buffer.append('[*] loc: %s\n'%sink_node["location"])
		print_buffer.append('[*] sink_type: %s\n'%(sink_node["sink_type"]))
		print_buffer.append('[*] sink_code: %s\n'%sink_node["sink_code"])

		json_flow_object = {
			"webpage": webpage_directory_hash,
			"script": script_name,
			"semantic_types": semantic_types_for_sink,
			"node_id": str(sink_node["id"]),
			"cfg_node_id": str(sink_node["cfg_node_id"]),
			"loc": sink_node["location"],
			"sink_type": sink_node["sink_type"],
			"sink_code": sink_node["sink_code"],
			"program_slices": {},
		}

		program_slices_dict = storage[sink_nid]["variables"]
		varnames = program_slices_dict.keys()
		counter = 1


		for varname in varnames:
			
			program_slices =  program_slices_dict[varname]["slices"]
			num_slices = len(program_slices)
			varname_semantic_types = program_slices_dict[varname]["semantic_types"]

			idx = 0
			for i in range(num_slices):
				idx +=1
				program_slice = program_slices[i]
				loc = _get_line_of_location(program_slice[3])
				code = program_slice[0]		

				if 'function(' in code:
					code = jsbeautifier.beautify(code) # pretty print function calls


				current_slice = { 
					"index": str(idx),
					"loc": loc,
					"code": code,
				}

				if i == 0 and varname in code:

					a = '\n%d:%s variable=%s\n'%(counter, str(varname_semantic_types), varname)
					counter += 1
					b = """\t%s (loc:%s)- %s\n"""%(str(idx), loc,code)
					print_buffer+= [a, b]

					if varname not in json_flow_object["program_slices"]:
						json_flow_object["program_slices"][varname] = {
							"semantic_types": varname_semantic_types, 
							"slices": [current_slice],
						}
					else:
						json_flow_object["program_slices"][varname]["slices"].append(current_slice)

				else:
					a = """\t%s (loc:%s)- %s\n"""%(str(idx), loc,code)
					print_buffer += [a]

					if varname not in json_flow_object["program_slices"]:
						json_flow_object["program_slices"][varname] = {
							"semantic_types": varname_semantic_types, 
							"slices": [current_slice],
						}
					else:
						json_flow_object["program_slices"][varname]["slices"].append(current_slice)

		json_buffer["flows"].append(json_flow_object)
		print_buffer.append('\n\n')
		print_buffer.append(sep_sub)

	output_file = os.path.join(webpage_directory, "sinks.flows.out")
	with open(output_file, "w+") as fd:
		for line in print_buffer:
			fd.write(line)

	output_file_json = os.path.join(webpage_directory, "sinks.flows.out.json")
	with open(output_file_json, "w+") as fd:
		json.dump(json_buffer, fd, ensure_ascii=False, indent=4)


	LOGGER.info('[TR] finished running the queries.')






	