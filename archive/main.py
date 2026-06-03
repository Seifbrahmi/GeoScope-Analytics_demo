import climate_aggregation
import merge_datasets
import spatial_aggregation
import temperature_aggregation


def main():
    print("Starting project...")
    spatial_aggregation.main()
    climate_aggregation.main()
    temperature_aggregation.main()
    merge_datasets.main()
    print("Project completed")


if __name__ == "__main__":
    main()
