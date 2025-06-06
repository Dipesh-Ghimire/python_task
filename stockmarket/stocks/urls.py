from django.urls import path
from . import views

urlpatterns = [
    # Other URL patterns...
    path('', views.company_list, name='company_list'),
    path('predict-future-prices/<int:id>/', views.predict_future_prices, name='predict_future_prices'),
    
    path('company/<int:id>/', views.company_detail, name='company_detail'),
    path('company/<int:id>/news/', views.company_news, name='company_news'),
    path('companies/create/', views.company_create, name='company_create'),

    path('company/<int:id>/price-history/', views.price_history, name='price_history'),
    path('news/', views.company_news_list, name='company_news_list'),
    path('news/add/', views.add_company_news, name='add_company_news'),
    path('news/<int:news_id>/', views.company_news_detail, name='company_news_detail'),

    path('prices/', views.price_history_list, name='price_history_list'),
    path('clear_prices/', views.delete_all_price_records, name='clear_pricehistory'),

    path('scrape-company-sharesansar/<int:id>/', views.scrape_sharesansar_pricehistory, name='scrape_price_sharesansar'),
    path('scrape-company-nepstock/<int:id>/', views.scrape_nepstock_pricehistory, name='scrape_price_nepstock'),
    path('scrape-company-merolagani/<int:id>/', views.scrpae_merolagani_pricehistory, name='scrape_price_merolagani'),

    path('floorsheet/<int:id>', views.list_floorsheet, name='floorsheet_list'),
    path('empty-floorsheet/<int:id>', views.empty_floorsheet, name='empty_floorsheet'),
    path('floorsheet/<int:id>/scrape-ss', views.scrape_floorsheet_ss, name='scrape_floorsheet_ss'),
    path('floorsheet/<int:id>/scrape-ns', views.scrape_floorsheet_nepstock, name='scrape_floorsheet_ns'),
    path('floorsheet/<int:id>/scrape-ml', views.scrape_floorsheet_ml, name='scrape_floorsheet_ml'),

    path('scrape-news-merolagani',views.scrape_news_ml, name='scrape_news_ml'),
    path('scrape-news-sharesansar',views.scrape_news_ss, name='scrape_news_ss'),
]
