# app/templatetags/querystring.py
from django import template

register = template.Library()

@register.simple_tag(takes_context=True)
def querystring(context, **kwargs):
    """
    Keep current GET parameters but override/add new ones.
    Usage: {% querystring sort='product_flow' %}
    """
    query = context['request'].GET.copy()
    for k, v in kwargs.items():
        query[k] = v
    return query.urlencode()
