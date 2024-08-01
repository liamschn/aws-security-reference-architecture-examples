import logging
import boto3
from boto3.dynamodb.conditions import Key, Attr
import os
import random
import string
from datetime import datetime
from time import sleep
import botocore


class sra_dynamodb:
    PROFILE = "default"
    UNEXPECTED = "Unexpected!"

    LOGGER = logging.getLogger(__name__)
    log_level: str = os.environ.get("LOG_LEVEL", "INFO")
    LOGGER.setLevel(log_level)

    def __init__(self, profile="default") -> None:
        self.PROFILE = profile
        try:
            if self.PROFILE != "default":
                self.MANAGEMENT_ACCOUNT_SESSION = boto3.Session(profile_name=self.PROFILE)
            else:
                self.MANAGEMENT_ACCOUNT_SESSION = boto3.Session()

            self.DYNAMODB_RESOURCE = self.MANAGEMENT_ACCOUNT_SESSION.resource("dynamodb")
        except Exception:
            self.LOGGER.exception(self.UNEXPECTED)
            raise ValueError("Unexpected error!") from None

    def create_table(self, table_name, dynamodb_client):
        # Define table schema
        key_schema = [
            {"AttributeName": "solution_name", "KeyType": "HASH"},
            {"AttributeName": "record_id", "KeyType": "RANGE"},
        ]  # Hash key  # Range key
        attribute_definitions = [
            {"AttributeName": "solution_name", "AttributeType": "S"},  # String type
            {"AttributeName": "record_id", "AttributeType": "S"},  # String type
        ]
        provisioned_throughput = {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5}

        # Create table
        try:
            dynamodb_client.create_table(
                TableName=table_name, KeySchema=key_schema, AttributeDefinitions=attribute_definitions, ProvisionedThroughput=provisioned_throughput
            )
            self.LOGGER.info(f"{table_name} dynamodb table created successfully.")
        except Exception as e:
            self.LOGGER.info("Error creating table:", e)
        # wait for the table to become active
        while True:
            wait_response = dynamodb_client.describe_table(TableName=table_name)
            if wait_response["Table"]["TableStatus"] == "ACTIVE":
                self.LOGGER.info(f"{table_name} dynamodb table is active")
                break
            else:
                self.LOGGER.info(f"{table_name} dynamodb table is not active yet. Status is '{wait_response['Table']['TableStatus']}'  Waiting...")
                # TODO(liamschn): need to add a maximum retry mechanism here
                sleep(5)

    def table_exists(self, table_name, dynamodb_client):
        # Check if table exists
        try:
            dynamodb_client.describe_table(TableName=table_name)
            self.LOGGER.info(f"{table_name} dynamodb table  already exists...")
            return True
        except dynamodb_client.exceptions.ResourceNotFoundException:
            self.LOGGER.info(f"{table_name} dynamodb table  does not exist...")
            return False

    def generate_id(self):
        new_record_id = str("".join(random.choice(string.ascii_letters + string.digits + "-_") for ch in range(8)))
        return new_record_id

    def get_date_time(self):
        now = datetime.now()
        return now.strftime("%Y%m%d%H%M%S")

    def insert_item(self, table_name, dynamodb_resource, solution_name):
        table = dynamodb_resource.Table(table_name)
        record_id = self.generate_id()
        date_time = self.get_date_time()
        response = table.put_item(
            Item={
                "solution_name": solution_name,
                "record_id": record_id,
                "date_time": date_time,
            }
        )
        # self.LOGGER.info({"insert_record_response": response})
        return record_id, date_time

    def update_item(self, table_name, dynamodb_resource, solution_name, record_id, attributes_and_values):
        table = dynamodb_resource.Table(table_name)
        update_expression = ""
        expression_attribute_values = {}
        for attribute in attributes_and_values:
            if update_expression == "":
                update_expression = "set " + attribute + "=:" + attribute
            else:
                update_expression = update_expression + ", " + attribute + "=:" + attribute
            expression_attribute_values[":" + attribute] = attributes_and_values[attribute]
        # self.LOGGER.info(f"update expression: {update_expression}")
        response = table.update_item(
            Key={
                "solution_name": solution_name,
                "record_id": record_id,
            },
            UpdateExpression=update_expression,
            ExpressionAttributeValues=expression_attribute_values,
            ReturnValues="UPDATED_NEW",
        )
        return response

    def find_item(self, table_name, dynamodb_resource, solution_name, additional_attributes):
        table = dynamodb_resource.Table(table_name)
        expression_attribute_values = {":solution_name": solution_name}

        filter_expression = " AND ".join([f"{attr} = :{attr}" for attr in additional_attributes.keys()])

        expression_attribute_values.update({f":{attr}": value for attr, value in additional_attributes.items()})

        query_params = {}

        query_params = {
            "KeyConditionExpression": "solution_name = :solution_name",
            "ExpressionAttributeValues": expression_attribute_values,
            "FilterExpression": filter_expression,
        }

        response = table.query(**query_params)

        if len(response["Items"]) > 1:
            self.LOGGER.info(
                f"Found more than one record that matched record id {response['Items'][0]['record_id']}.  Review {table_name} dynamodb table to determine cause."
            )
        elif len(response["Items"]) < 1:
            return False, None

        return True, response["Items"][0]

    def get_unique_values_from_list(self, list_of_values):
        unique_values = []
        for value in list_of_values:
            if value not in unique_values:
                unique_values.append(value)
        return unique_values

    def get_distinct_solutions_and_accounts(self, table_name, dynamodb_resource):
        table = dynamodb_resource.Table(table_name)
        response = table.scan()
        solution_names = [item["solution_name"] for item in response["Items"]]
        solution_names = self.get_unique_values_from_list(solution_names)
        accounts = [item["account"] for item in response["Items"]]
        accounts = self.get_unique_values_from_list(accounts)
        return solution_names, accounts

    def get_resources_for_solutions_by_account(self, table_name, dynamodb_resource, solutions, account):
        table = dynamodb_resource.Table(table_name)
        query_results = {}
        for solution in solutions:
            # expression_attribute_values = {":solution_name": solution}
            # filter_expression = {":account": account}

            query_params = {
                "KeyConditionExpression": "solution_name = :solution_name",
                "ExpressionAttributeValues": {":solution_name": solution, ":account": account},
                "FilterExpression": "account = :account",
            }

            response = table.query(**query_params)
            self.LOGGER.info(f"response: {response}")
            query_results[solution] = response
        return query_results