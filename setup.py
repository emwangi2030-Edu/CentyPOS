from setuptools import find_packages, setup

setup(
	name="centy_pos",
	version="1.0.0",
	description="Centy POS for East African SMEs on ERPNext v15",
	author="CentyHQ",
	author_email="edwin@getcenty.com",
	license="Proprietary",
	packages=find_packages(),
	zip_safe=False,
	include_package_data=True,
)
