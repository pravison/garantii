from stk_push import StkPushService
from b2c import B2CService

if __name__ == "__main__":
    # -------- STK PUSH --------
    stk = StkPushService(sandbox=False)
    stk_response = stk.initiate("254748800714", 1)

    checkout_id = stk_response.get("CheckoutRequestID")
    if checkout_id:
        stk.poll(checkout_id)

    # -------- B2C WITHDRAW --------
    b2c = B2CService(sandbox=False)
    b2c_response = b2c.withdraw("254748800714", 1)

    conversation_id = b2c_response.get("ConversationID")
    if conversation_id:
        b2c.poll(conversation_id)
