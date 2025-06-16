import azure.functions as func
import logging
import json
from shared.azure_services import AzureServices

azure_services = AzureServices()

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    try:
        req_body = req.get_json()
        
        # Extract parameters from request
        original_text = req_body.get('original_text')
        tone = req_body.get('tone')
        tone_description = req_body.get('tone_description')
        keywords = req_body.get('keywords')
        firm_name = req_body.get('firm_name')
        location = req_body.get('location')
        lawyer_name = req_body.get('lawyer_name')
        city = req_body.get('city')
        state = req_body.get('state')
        planning_session_name = req_body.get('planning_session_name', 'Life & Legacy Planning Session')

        # Generate content
        generated_content = azure_services.rewrite_content(
            original_text,
            tone,
            tone_description,
            keywords,
            firm_name,
            location,
            lawyer_name,
            city,
            state,
            planning_session_name
        )

        return func.HttpResponse(
            json.dumps({"content": generated_content}),
            mimetype="application/json",
            status_code=200
        )

    except Exception as e:
        logging.error(f"Error in content generation: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            mimetype="application/json",
            status_code=500
        )
