"""
/api/contact endpoint – pilot interest capture form.
"""

import logging
from fastapi import APIRouter
from models.schemas import ContactRequest, ContactResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Contact"])


@router.post("/contact", response_model=ContactResponse, summary="Submit pilot interest")
async def submit_contact(req: ContactRequest) -> ContactResponse:
    """
    Accept contact / pilot interest form submissions.

    Currently logs the submission. Will integrate CRM / email
    notifications in production.
    """
    logger.info(
        f"Contact submission: name={req.name} email={req.email} "
        f"company={req.company} pilot={req.pilot_interest}"
    )

    # TODO: Send to CRM (HubSpot, Salesforce) or email via SendGrid
    # TODO: Store in database for follow-up pipeline

    return ContactResponse(
        success=True,
        message=(
            f"Thanks {req.name}! We've received your message"
            + (" and will reach out about our pilot program." if req.pilot_interest else ".")
        ),
    )
