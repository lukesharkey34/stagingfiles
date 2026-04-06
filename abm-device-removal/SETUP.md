# ABM Device Removal Automation — Setup Guide

Self-service workflow for unassigning Apple devices from MDM via Apple Business Manager.

**Flow:** Microsoft Forms → Power Automate → Azure Function (Python) → ABM API

> **Important Limitation:** The ABM API can **unassign** devices from MDM servers but
> cannot fully **release/disown** devices from your organization. Full disown is only
> available through the ABM web portal at [business.apple.com](https://business.apple.com).
> For buyback scenarios, this automation handles the MDM unassign step. If full org
> release is needed, an admin completes that final step in the portal.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [ABM API Credentials](#2-abm-api-credentials)
3. [Azure Key Vault Setup](#3-azure-key-vault-setup)
4. [Azure Function Deployment](#4-azure-function-deployment)
5. [Microsoft Forms Design](#5-microsoft-forms-design)
6. [Power Automate Flow](#6-power-automate-flow)
7. [Testing](#7-testing)
8. [Optional Enhancements](#8-optional-enhancements)

---

## 1. Prerequisites

- **Azure subscription** with permission to create Function Apps and Key Vaults
- **Apple Business Manager** admin account with API access enabled
- **Microsoft 365** license with access to Forms and Power Automate (Premium license
  required for the HTTP connector in Power Automate)
- **Python 3.9+** for local development
- **Azure Functions Core Tools v4** (`npm install -g azure-functions-core-tools@4`)

---

## 2. ABM API Credentials

1. Log in to [business.apple.com](https://business.apple.com)
2. Go to **Settings** (bottom-left) → **API**
3. Click the **+** button to create a new API account
4. Download the **private key** file (`.p8` format, PEM-encoded P-256/ES256 key)
5. Note the following values:
   - **Client ID** — starts with `BUSINESSAPI.`
   - **Key ID** — displayed next to the key

> **Warning:** The private key can only be downloaded once. Store it securely immediately.

---

## 3. Azure Key Vault Setup

Store ABM credentials in Key Vault rather than plain-text app settings.

### Create secrets

In your Key Vault, create these secrets:

| Secret Name        | Value                                  |
|--------------------|----------------------------------------|
| `abm-private-key`  | Full PEM content of the `.p8` file     |
| `abm-client-id`    | Your ABM Client ID                     |
| `abm-key-id`       | Your ABM Key ID                        |

### Grant access to the Function App

1. In the Azure Portal, go to your **Function App** → **Identity**
2. Turn **ON** the System-assigned managed identity
3. Go to your **Key Vault** → **Access control (IAM)**
4. Add role assignment: **Key Vault Secrets User** → select the Function App's identity

---

## 4. Azure Function Deployment

### Local development

```bash
cd abm-device-removal

# Create virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Edit local.settings.json with your ABM credentials (for local testing only)

# Start the function locally
func start
```

The function will be available at: `http://localhost:7071/api/unassign-devices`

### Test locally with curl

```bash
curl -X POST http://localhost:7071/api/unassign-devices \
  -H "Content-Type: application/json" \
  -d '{
    "serial_numbers": "C02ABC123DEF, C02XYZ789GHI",
    "submitter_email": "test@company.com",
    "request_id": "test-001"
  }'
```

### Deploy to Azure

```bash
# Login
az login

# Create a Function App (if not already created)
az functionapp create \
  --resource-group <your-rg> \
  --consumption-plan-location <region> \
  --runtime python \
  --runtime-version 3.11 \
  --functions-version 4 \
  --name <your-function-app-name> \
  --storage-account <your-storage-account>

# Deploy
func azure functionapp publish <your-function-app-name>
```

### Configure app settings

In the Azure Portal → Function App → **Configuration**, add:

| Setting               | Value                                                                                       |
|-----------------------|---------------------------------------------------------------------------------------------|
| `ABM_CLIENT_ID`       | `@Microsoft.KeyVault(SecretUri=https://<vault>.vault.azure.net/secrets/abm-client-id/)`     |
| `ABM_KEY_ID`          | `@Microsoft.KeyVault(SecretUri=https://<vault>.vault.azure.net/secrets/abm-key-id/)`        |
| `KEY_VAULT_URL`       | `https://<vault>.vault.azure.net/`                                                          |
| `KEY_VAULT_SECRET_NAME` | `abm-private-key`                                                                         |

### Get the function URL and key

In Azure Portal → Function App → **Functions** → `unassign-devices` → **Get Function Url**

Copy the URL (includes the function key as a query parameter). You'll need this for Power Automate.

---

## 5. Microsoft Forms Design

Create a new form in [forms.office.com](https://forms.office.com):

**Form title:** Device Removal Request — ABM Unassign

### Fields

| #  | Field Name          | Type       | Required | Notes                                                           |
|----|---------------------|------------|----------|-----------------------------------------------------------------|
| 1  | Serial Numbers      | Long text  | Yes      | Instructions: "Enter serial numbers separated by commas or one per line" |
| 2  | Business Justification | Choice  | Yes      | Options: "Buyback", "End of Life", "Lost/Stolen", "Other"      |
| 3  | Additional Notes    | Long text  | No       | Optional context for the request                                |
| 4  | Confirmation        | Choice     | Yes      | "I confirm these devices should be unassigned from MDM" — Yes/No |

### Access control

- Click **Share** (top right) → set to **"Only people in my organization can respond"**
- To restrict further, use the form settings to limit to specific security groups
- The submitter's email is automatically captured by Microsoft 365 authentication

---

## 6. Power Automate Flow

Create an **Automated cloud flow** in [make.powerautomate.com](https://make.powerautomate.com).

### Step-by-step

#### Step 1: Trigger

- **Trigger:** "When a new response is submitted" (Microsoft Forms)
- **Form Id:** Select your "Device Removal Request" form

#### Step 2: Get response details

- **Action:** "Get response details" (Microsoft Forms)
- **Form Id:** Same form
- **Response Id:** Use the response ID from the trigger

#### Step 3: Check confirmation

- **Action:** Condition
- **Condition:** `Confirmation` is equal to `Yes`
- **If No:** Add "Send an email (V2)" action notifying the submitter that the request was
  not confirmed, then add a "Terminate" action with status "Cancelled"

#### Step 4: Call Azure Function (in the Yes branch)

- **Action:** HTTP (Premium connector)
- **Method:** POST
- **URI:** `https://<function-app>.azurewebsites.net/api/unassign-devices?code=<function-key>`
- **Headers:**
  ```
  Content-Type: application/json
  ```
- **Body:**
  ```json
  {
    "serial_numbers": "@{outputs('Get_response_details')?['body/rXXXXX']}",
    "submitter_email": "@{outputs('Get_response_details')?['body/responder']}",
    "request_id": "@{triggerOutputs()?['body/resourceData/responseId']}"
  }
  ```
  > Replace `rXXXXX` with the actual field ID for the Serial Numbers question.
  > To find it: add a "Compose" action, set input to the full Get response details output,
  > run the flow once, and inspect the output to see field IDs.

#### Step 5: Parse JSON response

- **Action:** Parse JSON
- **Content:** Body from the HTTP action
- **Schema:**
  ```json
  {
    "type": "object",
    "properties": {
      "request_id": { "type": "string" },
      "results": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "serial": { "type": "string" },
            "status": { "type": "string" },
            "error": { "type": "string" },
            "activity_id": { "type": "string" }
          }
        }
      },
      "summary": {
        "type": "object",
        "properties": {
          "total": { "type": "integer" },
          "succeeded": { "type": "integer" },
          "not_found": { "type": "integer" },
          "failed": { "type": "integer" },
          "invalid": { "type": "integer" }
        }
      },
      "limitation_notice": { "type": "string" }
    }
  }
  ```

#### Step 6: Email results to submitter

- **Action:** Send an email (V2) — Office 365 Outlook
- **To:** `@{outputs('Get_response_details')?['body/responder']}`
- **Subject:** `ABM Unassign Results — @{body('Parse_JSON')?['summary/succeeded']} of @{body('Parse_JSON')?['summary/total']} succeeded`
- **Body (HTML):**
  ```html
  <h3>Device Unassign Results</h3>
  <p><strong>Request ID:</strong> @{body('Parse_JSON')?['request_id']}</p>
  <p><strong>Total:</strong> @{body('Parse_JSON')?['summary/total']} |
     <strong>Succeeded:</strong> @{body('Parse_JSON')?['summary/succeeded']} |
     <strong>Failed:</strong> @{body('Parse_JSON')?['summary/failed']} |
     <strong>Not Found:</strong> @{body('Parse_JSON')?['summary/not_found']}</p>

  <table border="1" cellpadding="5">
    <tr><th>Serial</th><th>Status</th><th>Details</th></tr>
  </table>

  <!-- Use an "Apply to each" on body('Parse_JSON')?['results'] to build table rows -->

  <p><em>@{body('Parse_JSON')?['limitation_notice']}</em></p>
  ```

  > **Tip:** Use an "Apply to each" loop over `results` with an "Append to string variable"
  > action to build the HTML table rows, then insert the variable into the email body.

---

## 7. Testing

### Unit test the Azure Function

1. Start locally with `func start`
2. Send a test request with known serial numbers:
   ```bash
   curl -X POST http://localhost:7071/api/unassign-devices \
     -H "Content-Type: application/json" \
     -d '{"serial_numbers": "TESTSERIAL01", "submitter_email": "you@company.com", "request_id": "test-1"}'
   ```
3. Verify the response structure matches the expected format

### Test in Azure

1. Deploy the function
2. In the Azure Portal → Function App → Functions → `unassign-devices` → **Test/Run**
3. Paste a test JSON body and verify the response

### End-to-end test

1. Submit the Microsoft Form with a test serial number
2. Check the Power Automate flow run history for success/failure
3. Verify the results email was received
4. Confirm in the ABM portal that the device was unassigned

---

## 8. Optional Enhancements

### Approval workflow

Add a manager approval step before calling the Azure Function:

1. After the Condition (Step 3), add **"Start and wait for an approval"** action
2. Set approval type to "Approve/Reject — First to respond"
3. Assign to the submitter's manager (use Office 365 Users connector → "Get manager")
4. Add another Condition: if approved → call function; if rejected → notify submitter

### Audit logging

Add a SharePoint list or Excel Online table to log every request:

1. Create a SharePoint list with columns: Request ID, Submitter, Serials, Results, Timestamp
2. After the email step, add **"Create item"** (SharePoint) to log the request and results

### Teams notification

Send a summary to an IT admin Teams channel:

1. Add **"Post message in a chat or channel"** (Microsoft Teams) after the email step
2. Include the summary counts and any failures for admin visibility
