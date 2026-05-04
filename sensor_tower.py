    cutoff_date = (datetime.utcnow() - timedelta(days=release_lookback_days)).date()
    release_start_date = cutoff_date.isoformat()
    install_end_date = datetime.utcnow().date().isoformat()

    results: list[dict[str, Any]] = []

    for platform, category_ids in PUZZLE_CATEGORY_IDS.items():
        platform_app_ids: list[str] = []
        seen_app_ids: set[str] = set()

        for category_id in category_ids:
            app_ids = _fetch_app_ids_for_category(
                platform=platform,
                category_id=category_id,
                start_date=release_start_date,
                auth_token=config.sensor_tower_api_key,
            )
            for app_id in app_ids:
                if app_id not in seen_app_ids:
                    seen_app_ids.add(app_id)
                    platform_app_ids.append(app_id)

        if not platform_app_ids:
            logger.info("No app IDs found for platform=%s in the lookback window.", platform)
            continue

        install_map = _fetch_install_totals(
            platform=platform,
            app_ids=platform_app_ids,
            start_date=release_start_date,
            end_date=install_end_date,
            auth_token=config.sensor_tower_api_key,
        )
        if not install_map:
            logger.warning("No install data found for platform=%s.", platform)
            continue

        surviving_ids: list[str] = []
        for app_id, install_data in install_map.items():
            installs = int(install_data.get("installs_last_day", 0) or 0)
            if installs < min_installs:
                continue
            if max_installs is not None and installs > max_installs:
                continue
            surviving_ids.append(app_id)

        if not surviving_ids:
            logger.info(
                "No apps met the install threshold for platform=%s min_installs=%s.",
                platform,
                min_installs,
            )
            continue

        metadata_by_id = _fetch_metadata(
            platform=platform,
            app_ids=surviving_ids,
            auth_token=config.sensor_tower_api_key,
        )
        if not metadata_by_id:
            logger.warning("No metadata returned for platform=%s.", platform)
            continue

        for app_id in surviving_ids:
            metadata = metadata_by_id.get(app_id)
            installs = install_map.get(app_id)
            if metadata is None or installs is None:
                continue

            game_data = _combine_game_data(platform, app_id, installs, metadata)

            launch_raw = game_data.get("launch_date", "")
            if launch_raw:
                try:
                    launch_date = datetime.fromisoformat(
                        str(launch_raw).split("T")[0]
                    ).date()
                    if launch_date < cutoff_date:
                        logger.debug(
                            "Skipping %s — launch_date %s is older than cutoff %s",
                            game_data.get("name"),
                            launch_date,
                            cutoff_date,
                        )
                        continue
                except ValueError:
                    pass

            results.append(game_data)
