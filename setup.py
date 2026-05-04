from setuptools import setup, find_packages

setup(
    name="vendor-pricing",
    version="1.0.0",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "playwright>=1.44.0",
        "gspread>=6.1.2",
        "google-auth>=2.29.0",
        "click>=8.1.7",
        "rich>=13.7.1",
        "flask>=3.0.3",
        "python-dotenv>=1.0.1",
    ],
    entry_points={
        "console_scripts": [
            "vp=vendor_pricing.cli:cli",
        ],
    },
    python_requires=">=3.11",
)
