import aiohttp
import asyncio
import json
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

async def make_single_http_request(
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Makes a single HTTP request and returns a structured response or mock on error.
    """
    request_details = {
        "request_url": url,
        "request_method": method,
        "request_params": params if method == "GET" else None,
        "request_body": json_body if method in ["POST", "PUT", "PATCH"] else None,
        "request_headers": headers,
    }
    try:
        logger.info(f"🌍 Making {method} request to {url} with params={params}, body={json_body}, headers={headers}")
        async with session.request(
            method,
            url,
            params=params if method == "GET" else None,
            json=json_body if method in ["POST", "PUT", "PATCH"] else None,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
            ssl=False
        ) as response:
            response_data = None
            try:
                if response.content_type == 'application/json':
                    response_data = await response.json()
                else:
                    response_data = await response.text()
            except (aiohttp.ContentTypeError, json.JSONDecodeError) as json_err:
                logger.warning(f"⚠️ Could not parse JSON response from {url}: {json_err}. Reading as text.")
                response_data = await response.text()
            except Exception as e:
                logger.error(f"🚨 Error reading response content from {url}: {e}")
                response_data = f"Error reading response: {e}"

            logger.info(f"✅ Response from {url}: {response.status}")
            return {
                **request_details,
                "status_code": response.status,
                "response_headers": dict(response.headers),
                "response_data": response_data,
                "success": 200 <= response.status < 300,
            }
    except aiohttp.ClientConnectorError as e:
        logger.error(f"❌ Connection error for {url}: {e}")
        return {
            **request_details,
            "status_code": 503,
            "response_data": {"error": "Connection Error", "details": str(e)},
            "success": False,
            "mock_reason": "Connection Error",
        }
    except asyncio.TimeoutError:
        logger.error(f"⏰ Timeout error for {url}")
        return {
            **request_details,
            "status_code": 504,
            "response_data": {"error": "Timeout Error", "details": "Request timed out after 10 seconds"},
            "success": False,
            "mock_reason": "Timeout Error",
        }
    except Exception as e:
        logger.error(f"💥 Unexpected error for {url}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            **request_details,
            "status_code": 500,
            "response_data": {"error": "Unexpected Error", "details": str(e)},
            "success": False,
            "mock_reason": "Unexpected Error",
        }
