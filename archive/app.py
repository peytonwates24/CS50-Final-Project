from flask import Flask, render_template, request
import mysql.connector
from mysql.connector import Error
from flask import redirect, url_for

app = Flask(__name__)

# Establish a connection to the MySQL database
def create_connection():
    try:
        connection = mysql.connector.connect(
            host='localhost',      # Change this if your DB is hosted elsewhere
            database='form_results',  # Replace with your database name
            user='root',           # Your MySQL username
            password='Reddog1224'    # Your MySQL password
        )
        if connection.is_connected():
            print("Connected to MySQL database")
        return connection
    except Error as e:
        print("Error while connecting to MySQL", e)
        return None
    

@app.route('/submit_form', methods=['POST'])
def submit_form():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        message = request.form['message']
        
        # Insert the data
        insert_user(name, email)

        # Respond with a success message
        return render_template('forms.html', message="Thank you for your message! We will get back to you shortly.")


    

# Function to insert a new user
def insert_user(name, email):
    try:
        connection = create_connection()
        cursor = connection.cursor()
        query = "INSERT INTO contacts (name, email) VALUES (%s, %s)"
        data = (name, email)
        cursor.execute(query, data)
        connection.commit()  # Commit the transaction
        print(f"User {name} added successfully!")
    except Error as e:
        print(f"Error while inserting user: {e}")
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()



# Route for displaying the form
@app.route('/')
def index():
    return render_template('forms.html')

# Route to handle form submission
@app.route('/submit_form', methods=['POST'])
def submit_form():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        message = request.form['message']

        # For demonstration, we're just printing the submitted data
        print(f"Name: {name}")
        print(f"Email: {email}")
        print(f"Message: {message}")

        # You can add your form processing logic here, such as saving to a database or sending an email

        # Display a success message after form submission
        return render_template('forms.html', message="Thank you for your message! We will get back to you shortly.")

if __name__ == '__main__':
    app.run(debug=True)


