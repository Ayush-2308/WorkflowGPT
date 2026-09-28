"""Common n8n node types the agent may use when generating workflows."""

CATALOG = """
Triggers:
- n8n-nodes-base.webhook (v2): httpMethod, path, responseMode=onReceived
- n8n-nodes-base.scheduleTrigger (v1.2): rule.interval[] with field cronExpression or hours/days
- n8n-nodes-base.formTrigger (v2.2): formTitle, path, formFields.values[]
- n8n-nodes-base.emailReadImap (v2): mailbox polling; needs imap credential
- n8n-nodes-base.gmailTrigger (v1): google Gmail OAuth credential id
- n8n-nodes-base.telegramTrigger (v1): telegramApi credential
- n8n-nodes-base.slackTrigger (v1): slackApi credential
- n8n-nodes-base.googleSheetsTrigger (v1): googleSheetsOAuth2Api
- n8n-nodes-base.rssFeedRead (v1): url
- n8n-nodes-base.manualTrigger (v1): editor-only; also add a webhook so API can test

Core:
- n8n-nodes-base.httpRequest (v4.2): method, url, sendHeaders, headerParameters, sendBody, specifyBody=json, jsonBody, authentication + credentials
- n8n-nodes-base.if (v2.2): conditions.conditions[]
- n8n-nodes-base.switch (v3): rules
- n8n-nodes-base.code (v2): jsCode, mode=runOnceForAllItems
- n8n-nodes-base.set (v3.4): assignments
- n8n-nodes-base.merge (v3): mode
- n8n-nodes-base.wait (v1): amount, unit
- n8n-nodes-base.splitInBatches (v3)
- n8n-nodes-base.filter (v2)
- n8n-nodes-base.html (v1): html
- n8n-nodes-base.markdown (v1)
- n8n-nodes-base.convertToFile (v1.1)
- n8n-nodes-base.readBinaryFile (v1)
- n8n-nodes-base.function (legacy): prefer code

Apps (need credentials or user-supplied token via httpHeaderAuth):
- n8n-nodes-base.emailSend (v2.1): fromEmail, toEmail, subject, text/html, smtp credential
- n8n-nodes-base.gmail (v2): send email with google Gmail OAuth
- n8n-nodes-base.slack (v2.2): post message, slackApi
- n8n-nodes-base.telegram (v1.2): chatId, text, telegramApi
- n8n-nodes-base.discord (v2): webhook or bot
- n8n-nodes-base.googleSheets (v4): spreadsheet, sheet, googleSheetsOAuth2Api
- n8n-nodes-base.googleDrive (v3)
- n8n-nodes-base.notion (v2)
- n8n-nodes-base.airtable (v2)
- n8n-nodes-base.postgres (v2.5): insert/select
- n8n-nodes-base.mySql (v2.5)
- n8n-nodes-base.supabase (v1)
- n8n-nodes-base.redis (v1)
- n8n-nodes-base.hubspot (v2)
- n8n-nodes-base.pipedrive (v1)
- n8n-nodes-base.salesforce (v2)
- n8n-nodes-base.jira (v1)
- n8n-nodes-base.github (v1)
- n8n-nodes-base.openAi (v1) / @n8n/n8n-nodes-langchain.openAi
- n8n-nodes-base.twilio (v1)
- n8n-nodes-base.whatsApp (v1) / WhatsApp Business Cloud

If an official node is missing, use HTTP Request to that product's public API and ask for the API token.
"""
