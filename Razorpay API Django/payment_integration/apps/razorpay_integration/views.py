from django.shortcuts import render, get_object_or_404
from .models import Order
from django.views.decorators.csrf import csrf_exempt
import razorpay
from django.conf import settings
from .constants import PaymentStatus
import json
import logging

# Setup logger
logger = logging.getLogger(__name__)

# Razorpay Client
client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))


def home(request):
    return render(request, "index.html")


def order_payment(request):
    if request.method == "POST":
        name = request.POST.get("name")
        amount = request.POST.get("amount")

        try:
            # Create Razorpay order
            razorpay_order = client.order.create(
                {"amount": int(amount) * 100, "currency": "INR", "payment_capture": "1"}
            )

            # Save order in database
            order = Order.objects.create(
                name=name,
                amount=amount,
                provider_order_id=razorpay_order["id"],
                status=PaymentStatus.PENDING,  # Set initial status
            )

            # Dynamic callback URL
            callback_url = request.build_absolute_uri("/razorpay/callback/")

            return render(
                request,
                "payment.html",
                {
                    "callback_url": callback_url,
                    "razorpay_key": settings.RAZORPAY_KEY_ID,
                    "order": order,
                },
            )
        except Exception as e:
            logger.error(f"Error creating order: {e}")
            return render(request, "error.html", {"message": "Order creation failed."})

    return render(request, "payment.html")


@csrf_exempt
def callback(request):
    try:
        if "razorpay_signature" in request.POST:
            # Extract payment details
            response_data = request.POST.dict()
            payment_id = response_data.get("razorpay_payment_id", "")
            provider_order_id = response_data.get("razorpay_order_id", "")
            signature_id = response_data.get("razorpay_signature", "")

            # Get order from database
            order = get_object_or_404(Order, provider_order_id=provider_order_id)
            order.payment_id = payment_id
            order.signature_id = signature_id

            # Verify payment signature
            try:
                client.utility.verify_payment_signature(response_data)
                order.status = PaymentStatus.SUCCESS  # Mark as success
            except razorpay.errors.SignatureVerificationError:
                order.status = PaymentStatus.FAILURE  # Mark as failure

            order.save()

            return render(request, "callback.html", {"status": order.status})

        else:
            # Handle failed payment response
            error_data = json.loads(request.POST.get("error[metadata]", "{}"))
            payment_id = error_data.get("payment_id")
            provider_order_id = error_data.get("order_id")

            order = get_object_or_404(Order, provider_order_id=provider_order_id)
            order.payment_id = payment_id
            order.status = PaymentStatus.FAILURE
            order.save()

            return render(request, "callback.html", {"status": order.status})

    except Exception as e:
        logger.error(f"Error in payment callback: {e}")
        return render(request, "error.html", {"message": "Payment processing failed."})
