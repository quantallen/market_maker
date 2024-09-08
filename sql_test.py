import pymysql

# Configuration for the MySQL connection
db_config = {
    "host": "localhost",
    "user": "root",            # Replace with your MySQL username
    "password": "aql4au04",    # Replace with your MySQL password
    "database": "test_db"      # Replace with your MySQL database name
}

def connect_to_db():
    try:
        # Establish the connection
        connection = pymysql.connect(
            host=db_config["host"],
            user=db_config["user"],
            password=db_config["password"],
            database=db_config["database"]
        )
        print("Connection successful!")
        return connection
    except pymysql.MySQLError as e:
        print(f"Error connecting to MySQL: {e}")
        return None

def execute_query(connection, query):
    try:
        with connection.cursor() as cursor:
            cursor.execute(query)
            result = cursor.fetchall()
            return result
    except pymysql.MySQLError as e:
        print(f"Error executing query: {e}")
        return None

if __name__ == "__main__":
    # Connect to the database
    connection = connect_to_db()
    
    if connection:
        # Sample query to execute
        query = "SELECT * FROM crypto_spread_monitor LIMIT 10;"  # Replace 'your_table_name' with an actual table name
        
        # Execute the query
        result = execute_query(connection, query)
        
        # Print the results
        if result:
            for row in result:
                print(row)
        
        # Close the connection
        connection.close()