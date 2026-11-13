"""Blueprint registration."""


def register_blueprints(app):
    from routes.dashboard import bp as dashboard_bp
    from routes.articles import bp as articles_bp
    from routes.users import bp as users_bp
    from routes.calendar_push import bp as cal_push_bp
    from routes.summary import bp as summary_bp
    from routes.insights import bp as insights_bp
    from routes.data_mgmt import bp as data_bp
    from routes.settings import bp as settings_bp
    from routes.api_common import bp as api_bp
    from routes.predict import bp as predict_bp
    from routes.baseline import bp as baseline_bp
    from routes.competitor import bp as competitor_bp
    from routes.master import bp as master_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(articles_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(cal_push_bp)
    app.register_blueprint(summary_bp)
    app.register_blueprint(insights_bp)
    app.register_blueprint(data_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(predict_bp)
    app.register_blueprint(baseline_bp)
    app.register_blueprint(competitor_bp)
    app.register_blueprint(master_bp)
