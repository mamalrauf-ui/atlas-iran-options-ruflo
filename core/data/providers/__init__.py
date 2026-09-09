"""
core/data/providers/__init__.py

Registry مرکزی Providerها (بخش ۵ سند: «Provider Selection باید یک نقطه
مشخص داشته باشد»).

قبل از این تغییر، core/data_center.py مستقیماً TSETMCProvider را import
و hard-code می‌کرد و FimaProvider اصلاً در هیچ صفحه‌ای صدا زده نمی‌شد؛
هر صفحه دیگری هم اگر می‌خواست یک Provider اضافه کند باید همان الگو را
در جای دیگری تکرار می‌کرد. این ماژول یک نقطه واحد انتخاب Provider است؛
UI و Sync Layer باید از همینجا Provider بگیرند، نه با import مستقیم
کلاس‌ها در چند صفحه مختلف.

اضافه/حذف Provider = فقط این دیکشنری. بقیه پروژه دست‌نخورده می‌ماند.
"""
from __future__ import annotations

from core.data.providers.base import OptionsDataProvider, ProviderError
from core.data.providers.tsetmc import TSETMCProvider
from core.data.providers.fima import FimaProvider

# ترتیب یعنی اولویت نمایش در UI، نه اولویت Fallback خودکار (بخش ۵ سند:
# TSETMC اصلی و پیش‌فرض، FIMA به‌عنوان منبع تکمیلی Current + Historical).
PROVIDERS: dict[str, OptionsDataProvider] = {
    "tsetmc": TSETMCProvider(),
    "fima": FimaProvider(),
}


def get_provider(key: str) -> OptionsDataProvider:
    if key not in PROVIDERS:
        raise ValueError(f"Provider ناشناخته: «{key}». گزینه‌های موجود: {list(PROVIDERS)}")
    return PROVIDERS[key]


def list_providers() -> list[str]:
    return list(PROVIDERS.keys())


__all__ = ["OptionsDataProvider", "ProviderError", "TSETMCProvider", "FimaProvider",
           "PROVIDERS", "get_provider", "list_providers"]
