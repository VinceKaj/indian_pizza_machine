from pathlib import Path
from loguru import logger
import pandas as pd
import typer
from config import EXTERNAL_DATA_DIR

app = typer.Typer(no_args_is_help=True)

@app.command("load-musk-tweets")
def load_musk_tweets(input_dir: Path = EXTERNAL_DATA_DIR, file_name: str = "all_musk_posts.csv") -> pd.DataFrame:
    """
    Load data from a CSV file into a pandas DataFrame.

    Args:
        file_path (Path): The path to the CSV file.
    Returns:
        pd.DataFrame: The loaded data as a DataFrame.
    """
    file_path = input_dir / file_name
    logger.info(f"Loading data from {file_path}")
    try:
        data = pd.read_csv(file_path)
        logger.info(f"Data loaded successfully with shape {data.shape}")
        
        data.to_parquet(EXTERNAL_DATA_DIR / "all_musk_posts.parquet", index=False)
    

    except Exception as e:
        logger.error(f"Failed to load data: {e}")
        raise

@app.command("info")
def show_info():
    """Show information about available datasets."""
    logger.info(f"Data directory: {EXTERNAL_DATA_DIR}")
    logger.info("Available datasets: all_musk_posts.csv, musk_quote_tweets.csv")

if __name__ == "__main__":
    app()

