# ডাটাবেস ইউআরআল পরিবর্তন করুন (Railway PostgreSQL এর জন্য):
import os
import sys

# Railway PostgreSQL এর জন্য ডাটাবেস কনফিগারেশন
database_url = os.environ.get('DATABASE_URL', 'sqlite:///hoisting.db')
if database_url and database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url