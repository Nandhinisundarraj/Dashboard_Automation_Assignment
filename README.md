OrangeHRM Dashboard Automation

A simple web dashboard that triggers Selenium automation on the OrangeHRM demo site — login, add an employee, verify creation, extract the employee list, and logout.

Features:

HTML/CSS dashboard (Flask backend) to enter login credentials and employee details
One-click "Submit" triggers the automation flow
Shows inserted employee data and success/failure status back on the dashboard
Logs every automation step
Exports extracted employee data to CSV

Tech Stack:

Backend: Python, Flask
Automation: Selenium
Frontend: HTML, CSS
Data export: CSV

Setup:

Clone the repo and install dependencies:
bash
   pip install -r requirements.txt
Add your credentials to a .env file:
   ORANGEHRM_USERNAME=Admin
   ORANGEHRM_PASSWORD=admin123
Make sure Chrome + ChromeDriver (or your chosen browser driver) is installed and matches your browser version.
Running the App
bash
python app.py

Then open http://localhost:5000 in your browser.


How It Works:

Enter login credentials and employee details (First Name, Last Name, Employee ID) on the dashboard.
Click Submit.
The automation script:
Opens https://opensource-demo.orangehrmlive.com
Logs in with the provided credentials
Navigates to the PIM section
Adds the new employee
Verifies the employee was created successfully
Extracts the current employee list
Logs out
The dashboard displays the submitted employee details, a success/failure status, and (optionally) the extracted employee table.
