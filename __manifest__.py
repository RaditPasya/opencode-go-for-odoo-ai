{
    'name': 'AI Provider — Opencode Go',
    'version': '19.0.1.0.0',
    'category': 'Technical',
    'summary': 'Chat Completions provider for Odoo AI',
    'description': """
        Adds Opencode Go (and any OpenAI-compatible Chat Completion API)
        as an AI provider for Odoo's enterprise AI module.

        Uses Chat Completions API (POST /v1/chat/completions) instead
        of the Responses API, enabling compatibility with:
          - Opencode Go (opencode.ai/zen/go)
          - Any OpenAI-compatible endpoint (Ollama, vLLM, LocalAI, etc.)
    """,
    'author': '',
    'website': '',
    'license': 'LGPL-3',
    'depends': ['ai', 'ai_app', 'base_setup'],
    'data': [
        'security/ir.model.access.csv',
        'data/ai_available_model_data.xml',
        'views/res_config_settings_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ai_provider_opencode/static/src/composer_patch_fix.js',
        ],
    },
    'installable': True,
    'auto_install': False,
}
