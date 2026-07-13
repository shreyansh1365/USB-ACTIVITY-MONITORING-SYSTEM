# import mysql.connector
# from config import DB_CONFIG


# def get_connection():
#     """
#     Returns a MySQL database connection.
#     """

#     return mysql.connector.connect(
#     host=DB_CONFIG["host"],
#     port=DB_CONFIG["port"],
#     user=DB_CONFIG["user"],
#     password=DB_CONFIG["password"],
#     database=DB_CONFIG["database"]
# )
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
load_dotenv()


def get_connection():
    return psycopg2.connect(
        os.environ["DATABASE_URL"],
        cursor_factory=RealDictCursor
    )