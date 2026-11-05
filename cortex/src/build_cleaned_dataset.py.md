src/build_cleaned_dataset.py

# build_cleaned_dataset.py

build_cleaned_dataset.py exports _weather, _carbon, _aggregates, build, and main.

<!-- cortex-file -->

## _weather

No parameters go in. Sets frames to an empty list.

<!-- cortex-logic -->

## _carbon

No parameters go in. Sets start to f{START_DATE}T00.

<!-- cortex-logic -->

## _aggregates

weather goes in. Sets temp to weather[[f{city}_temperature_2m for city, _, _ in CITIES]].mean(axis=1.

<!-- cortex-logic -->

## build

No parameters go in. Calls load_dotenv with repo_root() / .env.

<!-- cortex-logic -->

## main

No parameters go in. Sets frame to the result of build.

<!-- cortex-logic -->

<!-- cortex-source-hash:ccecfa7230825dea25587518ee723c9fddb0088d9f112fd3b73fa5ad353c77e8 -->
