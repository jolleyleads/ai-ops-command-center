from src.campaign_measurement import score_lead, campaign_metrics, rate

def test_scores_only_supported_evidence():
    lead={"buying_signal":{"supported":True,"source_url":"https://example.org/evidence","points":30},
          "business_relevance":{"supported":True,"points":20},
          "decision_maker":{"supported":True,"source_url":"https://example.org/team","points":200}}
    output=score_lead(lead)
    assert output["score"] == 45
    assert output["breakdown"]["business_relevance"]["points"] == 0
    assert output["qualification_independent"] is True

def test_invalid_or_unknown_scores_are_zero():
    assert score_lead({"buying_signal":{"supported":True,"source_url":"x","points":-2}})["score"]==0
    assert score_lead({"buying_signal":{"supported":True,"source_url":"x","points":"30"}})["score"]==0

def test_rates_need_proven_denominator():
    assert rate(0,0) is None
    assert rate(2,5)==40
    assert rate(7,5) is None

def test_delivery_vs_sent_different():
    result=campaign_metrics({"sent":25,"delivered":20,"replies":5,"positive_replies":2,"booked":1,"contacted":25,"customers":1})
    assert result["reply_rate_per_sent"]==20
    assert result["reply_rate_per_delivered"] is None
    assert result["contact_to_customer_rate"]==4
    result=campaign_metrics({"sent":25,"delivered":20,"replies":5,"delivery_evidence":True})
    assert result["reply_rate_per_delivered"]==25
