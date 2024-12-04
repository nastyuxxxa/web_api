import asyncio
import re
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException
from parser import get_page
from starlette.concurrency import run_in_threadpool
from sqlmodel import Field, SQLModel, create_engine, Session, select


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("lifespan start")
    create_db_and_tables()
    await startup_event()
    yield
    print("lifespan end")


app = FastAPI(lifespan=lifespan)
PRICES_DB = []


class Prices(SQLModel, table=True):
    id: int = Field(primary_key=True)
    name: str
    cost: int


sqlite_url = "sqlite:///parser.db"
engine = create_engine(sqlite_url)


def get_session():
    with Session(engine) as session:
        yield session


SessionDep = Depends(get_session)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


def add_item(session: Session, title: str, price: int):
    existing_item = session.exec(select(Prices).where(Prices.name == title)).first()
    if not existing_item:
        new_item = Prices(name=title, cost=price)
        session.add(new_item)
        session.commit()
        session.refresh(new_item)
        print(f"Added to DB: {new_item}")
    else:
        print(f"Item already exists: {existing_item}")


def clean_price(price_str: str) -> int:
    cleaned_price = re.sub(r"\D", "", price_str)
    return int(cleaned_price)


async def background_parser_async():
    while True:
        print("Starting get price")
        items = await run_in_threadpool(get_page)
        with Session(engine) as session:
            for item in items:
                try:
                    price = clean_price(item["price"])
                    add_item(session, title=item["title"], price=price)
                except ValueError as e:
                    print(f"Error processing item: {item}. Error: {e}")
        print("Database updated!")
        await asyncio.sleep(12 * 60 * 60)


async def startup_event():
    asyncio.create_task(background_parser_async())


@app.get("/prices")
async def read_prices(session: Session = SessionDep, offset: int = 0, limit: int = 100):
    return session.exec(select(Prices).offset(offset).limit(limit)).all()


@app.get("/prices/{item_id}")
async def read_item(item_id: int, session: Session = SessionDep):
    price = session.get(Prices, item_id)
    if not price:
        raise HTTPException(status_code=404, detail="Price not found")
    return price


@app.put("/prices/{item_id}")
async def update_item(item_id: int, data: Prices, session: Session = SessionDep):
    price_db = session.get(Prices, item_id)
    if not price_db:
        raise HTTPException(status_code=404, detail="Price not found")
    price_data = data.model_dump(exclude_unset=True)
    price_db.sqlmodel_update(price_data)
    session.add(price_db)
    session.commit()
    session.refresh(price_db)
    return price_db


@app.post("/prices/create")
async def create_item(item: Prices, session: Session = SessionDep):
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


@app.delete("/prices/{item_id}")
async def delete_item(item_id: int, session: Session = SessionDep):
    price = session.get(Prices, item_id)
    if not price:
        raise HTTPException(status_code=404, detail="Price not found")
    session.delete(price)
    session.commit()
    return {"ok": True}
