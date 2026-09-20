from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

# Discovered by Tandoor (cookbook/urls.py:76-82) via `api_router_name`; register ViewSets on this
# router to expose them under the main /api/ router and in the generated OpenAPI client.
import_web_router = DefaultRouter()


urlpatterns = [
    path('recipe-from-source/', views.RecipeFromUrlView.as_view(), name='import-web-recipe-from-source'),
    path('recipe-from-video/', views.RecipeFromVideoView.as_view(), name='import-web-recipe-from-video'),
    path('recipe-from-video/transcribe/', views.VideoTranscribeView.as_view(), name='import-web-recipe-from-video-transcribe'),
    path('recipe-from-video/extract/', views.VideoExtractView.as_view(), name='import-web-recipe-from-video-extract'),
    path('image/<path:name>/', views.CachedImageView.as_view(), name='import-web-cached-image'),
]
