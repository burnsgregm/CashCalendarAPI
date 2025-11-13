
# Cash Calendar API

This is the secure **Backend API** for the Cash Calendar application.

It is a Python/Flask server that provides all data and authentication logic for the project. It uses Google OAuth 2.0 to authenticate users and a multi-tenant SQLite database to keep each user's financial data private.

This API is designed to be deployed to a service like **Render**. The frontend is in a separate repository (`CashCalendarUI`) and is deployed to **Netlify**.

## API Endpoints

All data endpoints require a valid `Bearer <JWT_TOKEN>` in the `Authorization` header.

* `/api/login`: (Public) Starts the Google OAuth login flow.
* `/auth/callback`: (Public) Handles the Google callback and issues a JWT.
* `/api/me`: (Protected) Returns the current user's email.
* `GET /api/settings`: (Protected) Gets the user's settings.
* `POST /api/settings`: (Protected) Updates the user's settings.
* `GET /api/calendar_data`: (Protected) Gets the calculated data for the calendar.
* `GET /api/transactions/<date>`: (Protected) Gets transactions for a specific day.
* `POST /api/transactions`: (Protected) Adds a new transaction.
* `GET /api/transaction/<id>`: (Protected) Gets a single transaction.
* `PUT /api/transactions/<id>`: (Protected) Updates a transaction.
* `DELETE /api/transactions/<id>`: (Protected) Deletes a transaction.
* `GET /api/schedules`: (Protected) Gets all recurring schedule rules.
* `POST /api/schedules`: (Protected) Adds a new schedule rule.
* `DELETE /api/schedules/<id>`: (Protected) Deletes a schedule rule.
* `GET /api/categories`: (Protected) Gets all categories.
* `POST /api/categories`: (Protected) Adds a new category.
* `PUT /api/categories/<id>`: (Protected) Updates a category.
* `DELETE /api/categories/<id>`: (Protected) Deletes a category.

## Deployment to Render

This repository is "Render-ready."

1.  Create a new "Web Service" on Render and connect this GitHub repository.
2.  Render will auto-detect the `render.yaml` file.
3.  Set the "Root Directory" to `./` (or leave blank).
4.  Under "Environment," add your secrets:
    * `GOOGLE_CLIENT_ID`
    * `GOOGLE_CLIENT_SECRET`
    * `JWT_SECRET_KEY`
    * `FRONTEND_URL` (Set this to your live Netlify app's URL)
5.  Click "Create Web Service." The app will build and deploy.
