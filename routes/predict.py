from flask import Blueprint, render_template, request, jsonify

from core.database import save_prediction, get_predictions, update_prediction_actuals

bp = Blueprint("predict", __name__)


@bp.route("/predict")
def predict_page():
    history = get_predictions(limit=50)
    prefill_title = (request.args.get("title") or "").strip()
    prefill_draft = (request.args.get("draft") or "").strip()
    prefill_source = (request.args.get("source") or "").strip()
    prefill_publish_date = (request.args.get("publish_date") or "").strip()
    prefill_publish_time = (request.args.get("publish_time") or "").strip()
    return render_template(
        "predict.html",
        history=history,
        prefill_title=prefill_title,
        prefill_draft=prefill_draft,
        prefill_source=prefill_source,
        prefill_publish_date=prefill_publish_date,
        prefill_publish_time=prefill_publish_time,
    )


@bp.route("/api/predict/save", methods=["POST"])
def api_predict_save():
    data = request.get_json(force=True)
    scores = data.get("scores", {})
    preds = data.get("predictions", {})
    row = {
        "title": data.get("title", ""),
        "a_score": scores.get("a"),
        "b_score": scores.get("b"),
        "c_score": scores.get("c"),
        "d_score": scores.get("d"),
        "e_score": scores.get("e"),
        "f_score": scores.get("f"),
        "g_score": scores.get("g"),
        "total_score": preds.get("total"),
        "path_type": preds.get("path", ""),
        "pred_reads": preds.get("readsRange", ""),
        "pred_rec_pct": preds.get("recRange", ""),
        "pred_read_rate": preds.get("readRateRange", ""),
        "pred_comments": preds.get("commentsRange", ""),
        "notes": data.get("notes", ""),
    }
    new_id = save_prediction(row)
    return jsonify({"ok": True, "id": new_id})


@bp.route("/api/predict/<int:pred_id>/actuals", methods=["PATCH"])
def api_predict_actuals(pred_id):
    data = request.get_json(force=True)
    ok = update_prediction_actuals(pred_id, data)
    return jsonify({"ok": ok})


@bp.route("/api/predict/history")
def api_predict_history():
    limit = int(request.args.get("limit", 50))
    return jsonify(get_predictions(limit=limit))
