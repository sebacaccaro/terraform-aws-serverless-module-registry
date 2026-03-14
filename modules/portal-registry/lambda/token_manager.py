"""Token CRUD operations against DynamoDB."""

import datetime
import secrets

import boto3


def create_token(table_name, name, permission):
    """Generate a secure random token and store it in DynamoDB."""
    ddb = boto3.resource("dynamodb")
    table = ddb.Table(table_name)

    token_value = secrets.token_hex()
    created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    item = {
        "token_value": token_value,
        "token_name": name,
        "permission": permission,
        "created_at": created_at,
    }
    table.put_item(Item=item)
    return item


def list_tokens(table_name):
    """List all tokens, excluding token values."""
    ddb = boto3.resource("dynamodb")
    table = ddb.Table(table_name)

    response = table.scan()
    items = response.get("Items", [])

    for item in items:
        item.pop("token_value", None)

    return items


def delete_token(table_name, token_name):
    """Delete a token by name."""
    ddb = boto3.resource("dynamodb")
    table = ddb.Table(table_name)

    response = table.query(
        IndexName="token_name-index",
        KeyConditionExpression=boto3.dynamodb.conditions.Key("token_name").eq(token_name),
    )
    items = response.get("Items", [])

    if not items:
        return None

    token_value = items[0]["token_value"]
    table.delete_item(Key={"token_value": token_value})
    return True


def get_token_by_name(table_name, token_name):
    """Look up a token by name using the GSI."""
    ddb = boto3.resource("dynamodb")
    table = ddb.Table(table_name)

    response = table.query(
        IndexName="token_name-index",
        KeyConditionExpression=boto3.dynamodb.conditions.Key("token_name").eq(token_name),
    )
    items = response.get("Items", [])

    if items:
        return items[0]
    return None
