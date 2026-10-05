# AURA Simulated Finance Portal

A lightweight standalone Next.js & TypeScript application simulating a corporate Accounts Payable / Finance Portal for autonomous agent testing and browser automation workflows.

## Features

- **Invoice Management**: Listing, searching, viewing, creating, and updating invoices.
- **REST API with CORS**: Complete JSON API endpoints for automation scripts and tools at `/api/finance/invoices`.
- **Realistic Validation & Error Handling**:
  - Missing required fields validation.
  - Invalid / non-positive amount detection.
  - Duplicate invoice ID prevention (HTTP 409).
- **Seeded Datasets**: Preloaded invoices for Acme Corp, Globex Logistics, and Nova Systems.

## Route Map

- `/finance` - Finance overview metrics and recent activity dashboard.
- `/finance/invoices` - Searchable invoices list with status badges and detail links.
- `/finance/invoices/new` - Manual invoice entry form with real-time error alerts.
- `/finance/invoices/[id]` - Invoice details and status update actions (`PENDING`, `PAID`, `CANCELLED`).
- `/api/finance/invoices` - GET (list/search `?q=...`) & POST (create).
- `/api/finance/invoices/[id]` - GET (detail) & PATCH (update).

## How to Start the Portal

### 1. Development Server
From the `company/finance` directory:
```bash
npm run dev
```
By default, the application runs on [http://localhost:3000](http://localhost:3000).

### 2. Production Build & Start
```bash
npm run build
npm start
```

### 3. Running Data Layer Tests
```bash
npm test
```
Runs unit tests covering invoice listing, searching, creation, update, duplicate rejection, and field validations.
