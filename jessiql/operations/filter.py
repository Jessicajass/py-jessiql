from collections import abc
from typing import Any, Union

import sqlalchemy as sa
import sqlalchemy.sql.operators
import sqlalchemy.sql.functions

import sqlalchemy.dialects.postgresql as pg  # TODO: FIXME: hardcoded dependency on Postgres!

from .base import Operation

from jessiql.query_object.filter import FilterExpressionBase, FieldExpression, BooleanExpression
from jessiql.query_object.resolve import resolve_filtering_field_expression
from jessiql import exc


class FilterOperation(Operation):
    def apply_to_statement(self, stmt: sa.sql.Select) -> sa.sql.Select:
        stmt = stmt.filter(*(
            self._compile_condition(condition)
            for condition in self.query.filter.conditions
        ))

        # Done
        return stmt

    def _compile_condition(self, condition: FilterExpressionBase) -> sa.sql.ColumnElement:
        if isinstance(condition, FieldExpression):
            return self._compile_field_condition(condition)
        elif isinstance(condition, BooleanExpression):
            return self._compile_boolean_conditions(condition)
        else:
            raise NotImplementedError(repr(condition))

    def _compile_field_condition(self, condition: FieldExpression) -> sa.sql.ColumnElement:
        # Resolve column
        condition.property = resolve_filtering_field_expression(self.target_Model, condition, where='filter')
        col, val = condition.property, condition.value

        # Case 1. Both column and value are arrays
        if condition.is_array and _is_array(val):
            # Cast the value to ARRAY[] with the same type that the column has
            # Only in this case Postgres will be able to handle them both
            val = sa.cast(pg.array(val), pg.ARRAY(col.type.item_type))

        # Case 2. JSON column
        if condition.is_json:
            # This is the type to which JSON column is coerced: same as `value`
            # Doc: "Suggest a type for a `coerced` Python value in an expression."
            coerce_type = col.type.coerce_compared_value('=', val)  # HACKY: use sqlalchemy type coercion
            # Now, replace the `col` used in operations with this new coerced expression
            col = sa.cast(col, coerce_type)

        # Done
        return self.use_operator(
            condition,
            col,  # column expression
            val,  # value expression
        )

    def _compile_boolean_conditions(self, condition: BooleanExpression) -> sa.sql.ColumnElement:
        # "$not" is special
        if condition.operator == '$not':
            criterion = sql_anded_together([
                self._compile_condition(c)
                for c in condition.clauses
            ])
            return sa.not_(criterion)
        # "$and", "$or", "$nor" share some steps so they're handled together
        else:
            # Compile expressions
            criteria = [self._compile_condition(c) for c in condition.clauses]

            # Build an expression for the boolean operator
            if condition.operator in ('$or', '$nor'):
                # for $nor, it will be negated later
                cc = sa.or_(*criteria)
            elif condition.operator == '$and':
                cc = sa.and_(*criteria)
            else:
                raise NotImplementedError(f'Unsupported boolean operator: {condition.operator}')

            # Put parentheses around it when there are multiple clauses
            cc = cc.self_group() if len(criteria) > 1 else cc

            # for $nor, we promised to negate the result.
            # We do it after enclosing it into parentheses
            if condition.operator == '$nor':
                return ~cc

            # Done
            return cc

    def use_operator(self, condition: FieldExpression, column_expression: sa.sql.ColumnElement, value: sa.sql.ColumnElement) -> sa.sql.ColumnElement:
        self._validate_operator_argument(condition)
        operator_lambda = self._get_operator_lambda(condition.operator, use_array=condition.is_array)

        return operator_lambda(
            column_expression,  # left operand
            value,  # right operand
            condition.value  # original value
        )

    def _get_operator_lambda(self, operator: str, *, use_array: bool) -> callable:
        try:
            if use_array:
                return self.ARRAY_OPERATORS[operator]
            else:
                return self.SCALAR_OPERATORS[operator]
        except KeyError:
            raise exc.QueryObjectError(f'Unsupported operator: {operator}')

    def _validate_operator_argument(self, condition: FieldExpression):
        operator = condition.operator

        # See if this operator requires array argument
        if operator in self.ARRAY_OPERATORS_WITH_ARRAY_ARGUMENT:
            if not _is_array(condition.value):
                raise exc.QueryObjectError(f'Filter: {operator} argument must be an array')

    # region Library

    # Operators for scalar (e.g. non-array) columns
    SCALAR_OPERATORS = {
        # operator => lambda column, value, original_value
        # `original_value` is to be used in conditions, because `val` can be an SQL-expression!
        '$eq': lambda col, val, oval: col == val,
        '$ne': lambda col, val, oval: col.is_distinct_from(val),  # (see comment below)
        '$lt': lambda col, val, oval: col < val,
        '$lte': lambda col, val, oval: col <= val,
        '$gt': lambda col, val, oval: col > val,
        '$gte': lambda col, val, oval: col >= val,
        '$prefix': lambda col, val, oval: col.startswith(val),
        '$in': lambda col, val, oval: col.in_(val),  # field IN(values)
        '$nin': lambda col, val, oval: col.notin_(val),  # field NOT IN(values)
        '$exists': lambda col, val, oval: col != None if oval else col == None,

        # Note on $ne:
        # We can't actually use '!=' here, because with nullable columns, it will give unexpected results.
        # {'name': {'$ne': 'brad'}} won't select a User(name=None),
        # because in Postgres, a '!=' comparison with NULL is... NULL, which is a false value.
    }

    # Operators for array columns
    ARRAY_OPERATORS = {
        # array value: Array equality
        # scalar value: ANY(array) = value
        '$eq': lambda col, val, oval: col == val if _is_array(oval) else col.any(val),
        # array value: Array inequality
        # scalar value: ALL(array) != value
        '$ne': lambda col, val, oval: col != val if _is_array(oval) else col.all(val, sa.sql.operators.ne),
        # field && ARRAY[values]
        '$in': lambda col, val, oval: col.overlap(val),
        # NOT( field && ARRAY[values] )
        '$nin': lambda col, val, oval: ~ col.overlap(val),
        # is not NULL
        '$exists': lambda col, val, oval: col != None if oval else col == None,
        # contains all values
        '$all': lambda col, val, oval: col.contains(val),
        # value == 0: ARRAY_LENGTH(field, 1) IS NULL
        # value != 0: ARRAY_LENGTH(field, 1) == value
        '$size': lambda col, val, oval: sa.sql.functions.func.array_length(col, 1) == (None if oval == 0 else val),
    }

    # List of operators that always require array argument
    ARRAY_OPERATORS_WITH_ARRAY_ARGUMENT = frozenset(('$all', '$in', '$nin'))

    # List of boolean operators that operate on multiple conditional clauses
    BOOLEAN_OPERATORS = frozenset(('$and', '$or', '$nor', '$not'))

    @classmethod
    def add_scalar_operator(cls, name: str, callable: abc.Callable[[sa.sql.ColumnElement, Any, Any], sa.sql.ColumnElement]):
        """ Add an operator that operates on scalar columns

        NOTE: This will add an operator that is effective application-wide, which is not good.
        The correct way to do it would be to subclass FilterOperation

        Args:
            name: Operator name. For instance: $search
            callable: A function that implements the operator.
                Accepts three arguments: column, processed_value, original_value
        """
        cls.SCALAR_OPERATORS[name] = callable

    @classmethod
    def add_array_operator(cls, name: str, callable: abc.Callable[[sa.sql.ColumnElement, Any, Any], sa.sql.ColumnElement]):
        """ Add an operator that operates on array columns """
        cls.ARRAY_OPERATORS[name] = callable

    # endregion


def _is_array(value):
    """ Is the provided value an array of some sorts (list, tuple, set)? """
    return isinstance(value, (list, tuple, set, frozenset))


def sql_anded_together(conditions: list[sa.sql.ColumnElement]) -> Union[sa.sql.ColumnElement, bool]:
    """ Take a list of conditions and join them together using AND. """
    # No conditions: just return True, which is a valid sqlalchemy expression for filtering
    if not conditions:
        return True

    # AND them together
    cc = sa.and_(*conditions)

    # Put parentheses around it, if necessary
    return cc.self_group() if len(conditions) > 1 else cc