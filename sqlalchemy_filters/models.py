from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.inspection import inspect
from sqlalchemy_utils import get_type, get_query_entities

from .exceptions import BadQuery, FieldNotFound, BadSpec


class Field(object):

    def __init__(self, model, field_name):
        self.model = model
        self.field_name = field_name

    def get_sqlalchemy_field(self):

        inspected = inspect(self.model)

        if '.' in self.field_name:
            model_field, related_field, = self.field_name.split('.')

            if model_field in inspected.relationships.keys():
                related_model = get_type(getattr(self.model, model_field))
                return getattr(related_model, related_field)

        elif self.field_name in inspected.columns.keys():
            return getattr(self.model, self.field_name)

        raise FieldNotFound(
            'Model {} has no column `{}`.'.format(
                self.model, self.field_name
            )
        )


def get_query_models(query):
    """Get models from query.

    :param query:
        A :class:`sqlalchemy.orm.Query` instance.

    :returns:
        A dictionary with all the models included in the query.
    """
    models = [col_desc['entity'] for col_desc in query.column_descriptions]
    models.extend(mapper.class_ for mapper in query._join_entities)
    return {
        model.__name__: model for model in models
    }


def get_model_from_spec(spec, query, default_model=None):
    """ Determine the model to which a spec applies on a given query.

    A spec that does not specify a model may be applied to a query that
    contains a single model. Otherwise the spec must specify the model to
    which it applies, and that model must be present in the query.

    :param query:
        A :class:`sqlalchemy.orm.Query` instance.

    :param spec:
        A dictionary that may or may not contain a model name to resolve
        against the query.

    :returns:
        A model instance.

    :raise BadSpec:
        If the spec is ambiguous or refers to a model not in the query.

    :raise BadQuery:
        If the query contains no models.

    """
    models = get_query_models(query)
    if not models:
        raise BadQuery('The query does not contain any models.')

    model_name = spec.get('model')
    if model_name is not None:
        models = [v for (k, v) in models.items() if k == model_name]
        if not models:
            raise BadSpec(
                'The query does not contain model `{}`.'.format(model_name)
            )
        model = models[0]
    else:
        if len(models) == 1:
            model = list(models.values())[0]
        elif default_model is not None:
            return default_model
        else:
            raise BadSpec(
                "Ambiguous spec. Please specify a model."
            )

    return model


def get_model_class_by_name(registry, name):
    """ Return the model class matching `name` in the given `registry`.
    """
    for cls in registry.values():
        if getattr(cls, '__name__', None) == name:
            return cls


def get_default_model(query):
    """ Return the singular model from `query`, or `None` if `query` contains
    multiple models.
    """
    query_models = get_query_models(query).values()
    if len(query_models) == 1:
        default_model, = iter(query_models)
    else:
        default_model = None
    return default_model

def implicit_join(query, model, filters):

    def filter_join(query, spec):
        if '.' in spec.filter_spec['field']:
            # achieves a join using - query(Parent).join(Parent.relation)
            field_name, relation_field_name = spec.filter_spec['field'].split('.')
            class_and_field = getattr(model, field_name)

            try:
                query = query.join( class_and_field )
            except InvalidRequestError as e:
                pass  # can't be autojoined

        return query

    for f1 in filters:
        if hasattr(f1, 'filters'):
            for f2 in f1.filters:
                if hasattr(f1, 'filters'):
                    query = filter_join(query, f2)
        else:
            query = filter_join(query, f1)

    return query
            
def auto_join(query, *model_names):
    """ Automatically join models to `query` if they're not already present
    and the join can be done implicitly.
    """
    # every model has access to the registry, so we can use any from the query
    query_models = get_query_models(query).values()
    model_registry = list(query_models)[-1]._decl_class_registry

    for name in model_names:
        model = get_model_class_by_name(model_registry, name)
        if model not in get_query_models(query).values():
            try:
                query = query.join(model)
            except InvalidRequestError:
                pass  # can't be autojoined
    return query
