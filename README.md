# Opportunity Navigator (Group Scalar prototype)

Run it:
1. Install Python 3.10 or newer, then run: pip install flask
2. In this folder run: python app.py
3. The first run creates navigator.db with fictional data and prints three demo accounts
   (student, staff, approver) with random passwords. Note them, they are shown once.
   To reset, delete navigator.db and run again.
4. Open http://127.0.0.1:5000

Optional: set the SECRET_KEY environment variable so logins survive a restart.

Demo journey: staff adds an opportunity, approver approves it, student searches and
filters, saves it to the wishlist, and sees the closed item labelled Closed.
