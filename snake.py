import curses
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from threading import Event, Lock, Thread
from typing import Any, List, Tuple, Type, Union


class Subscriber(ABC):
    @abstractmethod
    def event_received(self, event: object):
        pass


class Drawable(ABC):
    @abstractmethod
    def draw(self, win):
        pass


class Finalizer(ABC):
    @abstractmethod
    def finalize(self, message: str):
        pass


class Actionable(ABC):
    @abstractmethod
    def action(self):
        pass


class GameOver(Exception):
    pass


class Direction(Enum):
    LEFT = curses.KEY_LEFT
    RIGHT = curses.KEY_RIGHT
    UP = curses.KEY_UP
    DOWN = curses.KEY_DOWN


@dataclass
class SnakeElement(Drawable):
    y: int
    x: int

    def draw(self, win):
        win.addstr(self.y, self.x, 'X', curses.A_BOLD)


@dataclass
class Mouse(Drawable):
    y: int
    x: int

    def draw(self, win):
        win.addstr(self.y, self.x, 'M', curses.A_BOLD)

    def intersect(self, head: SnakeElement) -> bool:
        return self.x == head.x and self.y == head.y


class Info(Drawable, Finalizer):

    def __init__(self, top_y: int, top_x: int, height: int, width: int):
        self.top_y = top_y
        self.top_x = top_x
        self.height = height
        self.width = width
        self.score = 0
        self.game_over_message = ''

    def draw(self, win):
        # lower border
        for x in range(self.width):
            win.addstr(self.top_y + self.height - 1, x, '#', curses.A_BOLD)

        # left and right border
        for y in range(self.height):
            win.addstr(self.top_y + y, 0, '#', curses.A_BOLD)
            win.addstr(self.top_y + y, self.width - 1, '#', curses.A_BOLD)

        if not self.game_over_message:
            win.addstr(self.top_y + 1, 2, f'Score: {self.score}', curses.A_BOLD)
        else:
            win.addstr(self.top_y, 2, f'You {self.game_over_message} :(', curses.A_BOLD)
            win.addstr(self.top_y + 1, 2, f'Result: {self.score}', curses.A_BOLD)
            win.addstr(self.top_y + 2, 2, f'Press any key to exit', curses.A_BOLD)

    def finalize(self, message: str):
        self.game_over_message = message


class GameField:
    def __init__(self, width: int, height: int):
        self.cells = [[False for _ in range(width)] for _ in range(height)]
        self.width = width
        self.height = height

    def get_free_cell(self) -> Tuple[int, int]:
        free_cells = []
        for y in range(1, self.height - 2):
            for x in range(1, self.width - 2):
                if not self.cells[y][x]:
                    free_cells.append((y, x))
        if not free_cells:
            raise GameOver('win')
        return random.choice(free_cells)


class Border(Drawable):
    def __init__(self, height: int, width: int, game_field: GameField):
        self.game_field = game_field
        self.height = height
        self.width = width
        for x in range(self.width):
            self.game_field.cells[0][x] = True
            self.game_field.cells[self.height - 1][x] = True
        for y in range(self.height):
            self.game_field.cells[y][0] = True
            self.game_field.cells[y][self.width - 1] = True

    def draw(self, win):
        # upper and lower border
        for x in range(self.width):
            win.addstr(0, x, '#', curses.A_BOLD)
            win.addstr(self.height - 1, x, '#', curses.A_BOLD)

        # left and right border
        for y in range(self.height):
            win.addstr(y, 0, '#', curses.A_BOLD)
            win.addstr(y, self.width - 1, '#', curses.A_BOLD)


class GameWorld:
    def __init__(self, stdscr, win):
        self.game_objects = []
        self.stop = Event()
        self.input_processor = InputProcessor(stdscr, [], self.stop)
        self.input_processor.start()
        self.stdscr = stdscr
        self.win = win
        self.finalizers = []

    def add(self, game_object: Union[Actionable, Drawable, Subscriber]):
        self.game_objects.append(game_object)
        if isinstance(game_object, Subscriber):
            self.input_processor.add_subscriber(game_object)
        if isinstance(game_object, Finalizer):
            self.finalizers.append(game_object)

    def run(self):
        try:
            while True:
                self.win.clear()
                self._perform_actions()
                self._draw_objects()
                self.win.refresh()
                time.sleep(0.3)
        except GameOver as game_over:
            for finalizer in self.finalizers:
                finalizer.finalize(str(game_over))
            self._draw_objects()
            self.win.refresh()
            self.stop.set()
            self.input_processor.join()

    def get_game_object(self, game_object_type: Type) -> Union[Any, None]:
        for game_object in self.game_objects:
            if isinstance(game_object, game_object_type):
                return game_object

    def remove_game_object(self, game_object_type: Type):
        self.game_objects = [
            game_object for game_object in self.game_objects if not isinstance(game_object, game_object_type)
        ]

    def _perform_actions(self):
        for game_object in self.game_objects:
            if isinstance(game_object, Actionable):
                game_object.action()

    def _draw_objects(self):
        for game_object in self.game_objects:
            if isinstance(game_object, Drawable):
                game_object.draw(self.win)


class InputProcessor(Thread):
    def __init__(self, stdscr, subscribers: List[Subscriber], stop_event: Event):
        super().__init__(daemon=True, name='input_processor_thread')
        self.stdscr = stdscr
        self.subscribers = subscribers
        self.stop_event = stop_event

    def run(self):
        while not self.stop_event.is_set():
            new_char = self.stdscr.getch()
            for subscriber in self.subscribers:
                subscriber.event_received(new_char)

    def add_subscriber(self, subscriber: Subscriber):
        self.subscribers.append(subscriber)


class Snake(Subscriber, Drawable, Actionable):
    def __init__(self, game_field: GameField, game_world: GameWorld, info: Info):
        self.direction = Direction.RIGHT
        self.direction_lock = Lock()
        self.direction_changed = Event()
        self.info = info
        self.game_field = game_field
        self.game_world = game_world
        free_cell = self.game_field.get_free_cell()
        self.snake_elements = [SnakeElement(free_cell[0], free_cell[1])]
        self.game_field.cells[free_cell[0]][free_cell[1]] = True

    @property
    def head(self) -> SnakeElement:
        return self.snake_elements[0]

    def event_received(self, event: object):
        try:
            self.change_direction(Direction(event))
        except ValueError:
            pass

    def action(self):
        self.move()
        if self.game_world.get_game_object(Mouse).intersect(self.head):
            self.grow()
            self.info.score += 1
            self.game_world.remove_game_object(Mouse)
            self.game_world.add(Mouse(*self.game_field.get_free_cell()))
        self.direction_changed.clear()

    def change_direction(self, new_direction: Direction):
        # this method is called from input thread
        # self.direction also used in game loop thread (action method),
        # to prevent unexpected things - just lock it here
        with self.direction_lock:
            # this event is for those with fast hands, direction can be changed only once per game loop iteration
            if not self.direction_changed.is_set():
                if new_direction == Direction.RIGHT and self.direction not in {Direction.RIGHT, Direction.LEFT}:
                    self.direction = Direction.RIGHT
                elif new_direction == Direction.LEFT and self.direction not in {Direction.RIGHT, Direction.LEFT}:
                    self.direction = Direction.LEFT
                elif new_direction == Direction.UP and self.direction not in {Direction.UP, Direction.DOWN}:
                    self.direction = Direction.UP
                elif new_direction == Direction.DOWN and self.direction not in {Direction.UP, Direction.DOWN}:
                    self.direction = Direction.DOWN
                self.direction_changed.set()

    def grow(self):
        self.snake_elements.insert(0, SnakeElement(self.head.y, self.head.x))
        self._move_head()

    def move(self):
        self._move_tail()
        self._move_head()

    def draw(self, win):
        for snake_element in self.snake_elements:
            snake_element.draw(win)

    def _move_head(self):
        with self.direction_lock:
            if self.direction == Direction.RIGHT:
                self._move_right()
            elif self.direction == Direction.LEFT:
                self._move_left()
            elif self.direction == Direction.UP:
                self._move_up()
            elif self.direction == Direction.DOWN:
                self._move_down()
            self.game_field.cells[self.head.y][self.head.x] = True

    def _move_right(self):
        if self.game_field.cells[self.head.y][self.head.x + 1]:
            raise GameOver('bumped right')
        self.head.x = self.head.x + 1

    def _move_left(self):
        if self.game_field.cells[self.head.y][self.head.x - 1]:
            raise GameOver('bumped left')
        self.head.x = self.head.x - 1

    def _move_up(self):
        if self.game_field.cells[self.head.y - 1][self.head.x]:
            raise GameOver('bumped up')
        self.head.y = self.head.y - 1

    def _move_down(self):
        if self.game_field.cells[self.head.y + 1][self.head.x]:
            raise GameOver('bumped down')
        self.head.y = self.head.y + 1

    def _move_tail(self):
        prev_elem_x = self.snake_elements[0].x
        prev_elem_y = self.snake_elements[0].y
        for snake_element_idx in range(1, len(self.snake_elements)):
            tmp_x = self.snake_elements[snake_element_idx].x
            tmp_y = self.snake_elements[snake_element_idx].y
            self.snake_elements[snake_element_idx].x = prev_elem_x
            self.snake_elements[snake_element_idx].y = prev_elem_y
            self.game_field.cells[prev_elem_y][prev_elem_x] = True
            prev_elem_x, prev_elem_y = tmp_x, tmp_y
        self.game_field.cells[prev_elem_y][prev_elem_x] = False


def main(stdscr):
    game_border_height = 8
    game_border_width = 26
    info_border_height = 4

    stdscr.clear()
    win = curses.newwin(game_border_height + info_border_height + 1, game_border_width + 1, 0, 0)
    win.nodelay(True)
    win.keypad(True)

    game_world = GameWorld(stdscr, win)
    game_field = GameField(game_border_width, game_border_height)
    info_border = Info(game_border_height, 0, info_border_height, game_border_width)
    game_world.add(info_border)
    game_world.add(Border(game_border_height, game_border_width, game_field))
    game_world.add(Snake(game_field, game_world, info_border))
    game_world.add(Mouse(*game_field.get_free_cell()))

    game_world.run()


curses.wrapper(main)
