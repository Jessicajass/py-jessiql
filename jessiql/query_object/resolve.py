""" Tools to resolve query object references into actual SqlAlchemy attributes

These methods take QueryObject classes and "resolve" them: populate them with information from SqlAlchemy models
"""

from __future__ import annotations

from functools import singledispatch

from sqlalchemy.orm import (  # type: ignore[attr-defined]  # sqlalchemy stubs not updated
    InstrumentedAttribute,
)

from jessiql.sainfo.columns import resolve_column_by_name, is_array, is_json
from jessiql.sainfo.relations import resolve_relation_by_name
from jessiql.typing import SAModelOrAlias

from .query_object import QueryObject
from .select import SelectQuery, SelectedField, SelectedRelation
from .sort import SortQuery, SortingField
from .filter import FilterQuery, FieldFilterExpression, BooleanFilterExpression


# region Resolve operations' inputs

@singledispatch
def resolve_input(_, Model: SAModelOrAlias, *, where: str):
    """ Resolve input: a Query Object, or any of its operation's inputs

   This operation, given a specific Model class or aliased class, gathers additional information
   for actual columns and fields.

    Supports:
    * Query Object
    * Select operation
    * Sort operation
    * Filter operation
    """
    raise NotImplementedError(_)


@resolve_input.register
def resolve_query_object(query: QueryObject, Model: SAModelOrAlias):
    # Resolve every operation
    resolve_select(query.select, Model, where='select')
    resolve_sort(query.sort, Model, where='sort')
    resolve_filter(query.filter, Model, where='filter')


@resolve_input.register
def resolve_select(select: SelectQuery, Model: SAModelOrAlias, *, where: str):
    # Resolve fields
    for field in select.fields.values():
        resolve_selected_field(field, Model, where=where)

    # Resolve relations
    for relation in select.relations.values():
        resolve_selected_relation(relation, Model, where=where)


@resolve_input.register
def resolve_sort(sort: SortQuery, Model: SAModelOrAlias, *, where: str):
    # Resolve every sorting field
    for field in sort.fields:
        resolve_sorting_field(field, Model, where=where)


@resolve_input.register
def resolve_filter(filter: FilterQuery, Model: SAModelOrAlias, *, where: str):
    # Resolve every filtering condition
    for condition in filter.conditions:
        resolve_input_element(condition, Model, where=where)

# endregion

# region Resolve individual elements

@singledispatch
def resolve_input_element(_, Model: SAModelOrAlias, *, where: str):
    """ Resolve a specific element for the Query Object

    Supports:
    * Selected field
    * Selected relation
    * Sorting field
    * Filtering boolean expression
    * Filtering field expression
    """
    raise NotImplementedError(_)


@resolve_input_element.register
def resolve_selected_field(field: SelectedField, Model: SAModelOrAlias, *, where: str):
    # Get the attribute
    attribute = resolve_column_by_name(field.name, Model, where=where)

    # Populate the missing fields
    field.property = attribute.property
    field.is_array = is_array(attribute)
    field.is_json = is_json(attribute)


@resolve_input_element.register
def resolve_selected_relation(field: SelectedRelation, Model: SAModelOrAlias, *, where: str):
    # Get the attribute
    attribute = resolve_relation_by_name(field.name, Model, where=where)

    # Populate the missing fields
    field.property = attribute.property
    assert field.property.uselist is not None  # initialized and properly configured
    field.uselist = field.property.uselist


@resolve_input_element.register
def resolve_sorting_field(field: SortingField, Model: SAModelOrAlias, *, where: str):
    # Get the attribute
    attribute = resolve_column_by_name(field.name, Model, where=where)

    # Populate the missing fields
    field.property = attribute.property


@resolve_input_element.register
def resolve_filtering_boolean_expression(expression: BooleanFilterExpression, Model: SAModelOrAlias, *, where: str):
    # Iterate expressions, resolve them
    # Use `resolve_input_element()` because it might be a filter or a boolean expression
    for clause in expression.clauses:
        resolve_input_element(clause, Model, where=where)


@resolve_input_element.register
def resolve_filtering_field_expression(expression: FieldFilterExpression, Model: SAModelOrAlias, *, where: str):
    # Get the attribute the expression refers to
    attribute = resolve_column_by_name(expression.field, Model, where=where)

    # Populate the missing fields
    expression.property = attribute.property
    expression.is_array = is_array(attribute)
    expression.is_json = is_json(attribute)

# endregion
