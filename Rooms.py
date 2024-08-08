from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import create_engine, Column, Integer, String, Table, ForeignKey, func, DateTime
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, Session
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from typing import Dict, List
import json

SQLALCHEMY_DATABASE_URL = "postgresql://postgres:root@127.0.0.1:5432/message_app"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

room_participants = Table(
    'room_participants', Base.metadata,
    Column('room_id', Integer, ForeignKey('room.id'), primary_key=True),
    Column('user_id', Integer, ForeignKey('user.id'), primary_key=True)
)

class Room(Base):
    __tablename__ = "room"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    owner = Column(Integer, ForeignKey("user.id"))
    participants = relationship('User', secondary=room_participants, back_populates='rooms')

class User(Base):
    __tablename__ = "user"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    rooms = relationship('Room', secondary=room_participants, back_populates='participants')

class Message(Base):
    __tablename__ = "message"
    id = Column(Integer, primary_key=True, index=True)
    content = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    owner = Column(Integer, ForeignKey("user.id"))
    room = Column(Integer, ForeignKey("room.id"))



class RoomCreate(BaseModel):
    owner: int
    name: str

class RoomResponse(BaseModel):
    id: int
    name: str
    owner: int
    participants: int

class UserCreate(BaseModel):
    name: str

class MessageCreate(BaseModel):
    content: str
    owner: int
    room: int


class MessageResponse(BaseModel):
    id: int
    content: str
    created_at: datetime
    owner: int
    room: int


Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.post("/create/room/")
def create_room(room: RoomCreate, db = Depends(get_db)):
    user = db.query(User).filter(User.id == room.owner).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    new_room = Room(name=room.name, owner=user.id)
    db.add(new_room)
    db.commit()
    db.refresh(new_room)
    return new_room


@app.get("/rooms/")
def get_rooms(db = Depends(get_db)):
    room = db.query(Room).all()
    if room is None:
        raise HTTPException(status_code=404, detail="User not found")

    return room 

@app.get("/rooms/{room_id}")
def get_room_by_id(room_id: int, db = Depends(get_db)):
    room = db.query(Room).filter(Room.id == room_id).first()
    
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    
    return room

@app.get("/rooms/{id}")
def get_rooms_by_user_id(user_id : int, db = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    rooms = user.rooms
    
    if not rooms:
        raise HTTPException(status_code=404, detail="No rooms found for this user")
    
    return rooms

@app.post("/create/user/")
def create_user(user: UserCreate, db = Depends(get_db)):
    if db.query(User).filter(User.name == user.name).first():
        return db.query(User).filter(User.name == user.name).first()
    new_user = User(name=user.name)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


@app.post("/create/message/")
def create_message(message: MessageCreate, db = Depends(get_db)):
    room = db.query(Room).filter(Room.id == message.room).first()
    user = db.query(User).filter(User.id == message.owner).first()
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    new_room = Message(content=message.content, owner=user.id, room=room.id)
    db.add(new_room)
    db.commit()
    db.refresh(new_room)

    return new_room

@app.get("/users/{user_id}")
def get_user_by_id(user_id: int, db = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return user

@app.get("/users/")
def get_users(db = Depends(get_db)):
    users = db.query(User).all()
    
    if not users:
        raise HTTPException(status_code=404, detail="No users found")
    
    return users

@app.get("/rooms/{room_id}/messages/", response_model=List[MessageResponse])
def get_messages_by_room(room_id: int, db: Session = Depends(get_db)):
    messages = db.query(Message).filter(Message.room == room_id).all()
    
    if not messages:
        raise HTTPException(status_code=404, detail="No messages found for this room")
    
    return messages



active_connections: Dict[int, List[WebSocket]] = {}
active_connections_rooms: Dict[int, List[WebSocket]] = {}

@app.websocket("/ws/{room_id}/{user_id}")
async def websocket_endpoint(room_id: int, user_id: int,websocket: WebSocket, db = Depends(get_db)):
    room = db.query(Room).filter(Room.id == room_id).first()
    user = db.query(User).filter(User.id == user_id).first()

    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    await websocket.accept()

    if room_id not in active_connections:
        active_connections[room_id] = []
    active_connections[room_id].append(websocket)

    try:
        while True:
            data = await websocket.receive_text()
            new_message = Message(content=data, owner=user.id, room=room.id)
            db.add(new_message)
            db.commit()
            db.refresh(new_message)
            response = {
                "id": new_message.id,
                "owner": user.id,
                "room": room.id,
                "content": new_message.content,
                "created_at": new_message.created_at.isoformat()
            }
            
            for connection in active_connections[room_id]:
                await connection.send_text(json.dumps(response))

    except WebSocketDisconnect:
        active_connections[room_id].remove(websocket)


@app.websocket("/ws/rooms/{user_id}/")
async def websocket_rooms(user_id: int, websocket: WebSocket, db = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()

    await websocket.accept()

    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if user_id not in active_connections_rooms:
        active_connections_rooms[user_id] = []
    active_connections_rooms[user_id].append(websocket)

    try:
        while True:
            data = await websocket.receive_text()
            print(data)
            new_room = Room(name=data, owner=user.id)
            db.add(new_room)
            db.commit()
            db.refresh(new_room)
            response = {
                "id": new_room.id,
                "name": new_room.name,
                "owner": new_room.owner,
            }
            for connection in active_connections_rooms[user_id]:
                await connection.send_text(json.dumps(response))

    except WebSocketDisconnect:
        active_connections_rooms[user_id].remove(websocket)

    