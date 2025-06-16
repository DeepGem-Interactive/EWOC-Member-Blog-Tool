import azure.functions as func
import logging
import json
from shared.azure_services import AzureServices

azure_services = AzureServices()

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Content editor function processed a request.')

    try:
        req_body = req.get_json()
        
        session_id = req_body.get('session_id')
        user_message = req_body.get('user_message')
        current_content = req_body.get('current_content')
        
        if not all([session_id, user_message, current_content]):
            return func.HttpResponse(
                "Missing required parameters",
                status_code=400
            )

        edited_content = azure_services.edit_content(
            session_id,
            user_message,
            current_content
        )

        return func.HttpResponse(
            json.dumps({"edited_content": edited_content}),
            mimetype="application/json",
            status_code=200
        )

    except Exception as e:
        logging.error(f"Content editing failed: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            mimetype="application/json",
            status_code=500
        )