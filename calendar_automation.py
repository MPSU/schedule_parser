# -----------------------------------------------------------------------------
# Project Name   : MIET schedule parser
# Organization   : National Research University of Electronic Technology (MIET)
# Department     : Institute of Microdevices and Control Systems
# Author(s)      : Andrei Solodovnikov
# Email(s)       : hepoh@org.miet.ru
#
# See https://github.com/MPSU/schedule_parser/blob/master/LICENSE file for
# licensing details.
# ------------------------------------------------------------------------------
from functools import total_ordering
import requests
import json
from icalendar import Calendar, Event
from datetime import datetime, timedelta
from uuid import uuid4
import re

# Для работы скрипты требуется сторонняя библиотека icalendar, которую можно
# установить командой pip install icalendar

# Перед запуском скрипта, необходимо указать режим работы (для студента или
# для преподавателя), а также группу/группы, преподавателя и дату начала
# семестра.

# В режиме работы для студента скрипт парсит расписание только одной группы и
# создает расписание всех её занятий.
# В режиме работы для преподавателя скрипт парсит расписание всех указанных
# групп и создает расписание тех занятий, которые ведет указанный преподаватель
# у этих групп.

# В скрипте можно настроить длину академического часа, а также длинной и
# короткой перемен.

# Кроме того, в скрипте можно указать словарь для замены длинных названий
# на удобные пользователю аббревиатуры.

###############################################################################
# Область конфигурации
###############################################################################
educator_mode = True
group = ""
educator = "Солодовников Андрей Павлович"
groups = ["ИВТ-31В", "ПИН-32", "ПИН-33", "ПИН-34"]
academic_hour_duration = 40
short_recreation_duration = 10
long_recreation_duration = 40
semester_starts_at = "05-02-2024"
class_names_cast = {
  "Микропроцессорные средства и системы" : "МПСиС",
  "Микропроцессорные системы и средства" : "МПСиС"
}
calendar_file_name = "schedule.ics"
repeat_number      = 5
###############################################################################



###############################################################################
# Для работы с апи МИЭТоского расписания, необходимо сперва получить печеньку
# (куку).
# Видимо, это своеобразная защита от роботов :\
# Печеньку можно получить в браузерных инструментах разработчика при открытии
# любого расписания, либо же данной частью скрипта.
###############################################################################
url = "https://miet.ru/schedule/data"
cookie_response = raw_schedule = requests.get(url=url)
cookie = None
# Если печенька не задана, используем регулярное выражение для получения
# печеньки из get-запроса.
# Печенька представляет из себя строку вида wl=abcdef0123456789abcdef0123456789;
if not cookie:
  cookie_reg_expr = re.search(r'wl=[a-f0-9]+;', cookie_response.text)
  if cookie_reg_expr:
    cookie = {
      "Cookie": cookie_reg_expr.group(0)
    }
  else:
    print("Не удалось получить печеньку, попробуйте прописать ее вручную")
    exit()
###############################################################################



###############################################################################
# Класс записи занятия в расписании
# Использует поля, позволяющие однозначно идентифицировать запись, а также
# методы для сравнения записей, вывода их в текстовом виде в консоль и
# проверки на то, что одно занятие является продолжением другого (для
# объединения двойных и более пар в одно занятие).
###############################################################################
@total_ordering
class ScheduleEntry:
  def __init__(self, class_name, week_code, room_number, week_day, slot_number):
    self.class_name   = class_name  # Название пары
    self.week_code    = week_code   # Код недели:  0 — "1-ый числитель",
                                    #              3 — "2-ой знаменатель"
    self.room_number  = room_number # Номер аудитории
    self.week_day     = week_day    # День недели (отсчет ведется с нуля)
    self.slot_number  = slot_number # Номер пары  (отсчет ведется с нуля)
    self.duration     = 1           # Длительность занятия в парах

  def __eq__(self, other):
    if isinstance(other, ScheduleEntry):
      return (self.week_code, self.week_day, self.slot_number, self.room_number, self.class_name) == \
             (other.week_code, other.week_day, other.slot_number, other.room_number, other.class_name)
    return NotImplemented

  def __lt__(self, other):
    if isinstance(other, ScheduleEntry):
      return (self.week_code, self.week_day, self.slot_number, self.room_number, self.class_name) < \
             (other.week_code, other.week_day, other.slot_number, other.room_number, other.class_name)
    return NotImplemented

  def is_aligned_class(self, other):
    return self.class_name   == other.class_name and \
            self.week_code   == other.week_code and \
            self.week_day    == other.week_day and \
            self.room_number == other.room_number and \
            abs(self.slot_number - other.slot_number) == 1

  def __repr__(self):
    return f"\n{self.class_name}\n\tweek_code  : {self.week_code}\n\tweek_day   : {self.week_day}\n\troom_number: {self.room_number}\n\tduration   : {self.duration}"
###############################################################################



###############################################################################
# Функция, формирующая название занятия для записи в календаре.
# Позволяет изменить название на аббревиатуру из словаря.
###############################################################################
def get_class_name(name):
  long_name  = name
  class_type = ""
  res_name   = ""
  if " [" in name:
    class_type += " [" + name.split(" [")[1]
    long_name = long_name.replace(class_type, "")
  if long_name in class_names_cast:
    res_name += class_names_cast[long_name]
  else:
    res_name += long_name
  res_name += class_type
  return res_name
###############################################################################



###############################################################################
# Функция, формирующая список занятий, для указанных групп указанного
# преподавателя.
# Проходится по всем занятиям всех указанных групп, и если это занятие ведет
# указанный преподаватель, добавляет это занятие в итоговый список
###############################################################################
def create_list_of_classes_by_educator(groups, educator, url, cookie):
  class_list = []
  for group in groups:
    args = {"group":group}
    raw_schedule = requests.get(url=url, params = args, headers = cookie).json()["Data"]
    for double_class in raw_schedule:
      if double_class["Class"]["TeacherFull"] == educator:
        class_list.append(ScheduleEntry(
                            get_class_name(double_class["Class"]["Name"]) + " " + group,
                            double_class["DayNumber"] ,
                            double_class["Room"]["Name"],
                            double_class["Day"] - 1,         # приводим поля
                            double_class["Time"]["Code"] - 1 # к нумерации с нуля
                            )
                          )
  return class_list
###############################################################################



###############################################################################
# Функция, формирующая список всех занятий указанной группы
###############################################################################
def create_list_of_classes_by_group(group, url, cookie):
  class_list = []
  args = {"group":group}
  raw_schedule = requests.get(url=url, params = args, headers = cookie).json()["Data"]
  for double_class in raw_schedule:
    class_list.append(ScheduleEntry(
                        get_class_name(double_class["Class"]["Name"]),
                        double_class["DayNumber"],
                        double_class["Room"]["Name"],
                        double_class["Day"] - 1,         # приводим поля
                        double_class["Time"]["Code"] - 1 # к нумерации с нуля
                        )
                      )
  return class_list
###############################################################################



###############################################################################
# Функция, объединяющая двойные и более пары в одну запись.
# Объединяются соседние пары с одинаковым названием, проходящие в один день и
# один тип недели.
# Занятия вида "МПСиС [Лаб] ИВТ-31В" и "МПСиС [Лек] ИВТ-31В" объединены не будут
# даже если они соседние, поскольку названия у них различаются. Тоже самое
# произойдет, если названия полностью одинаковые, но пары не соседние (если
# между ними окно или другая пара).
###############################################################################
def merge_list_of_classes(class_list):
  class_list.sort()
  i = 0
  list_len = len(class_list)
  while_cond = True
  while while_cond:
    if(class_list[i].is_aligned_class(class_list[i+1])):
      class_list[i].duration += 1
      del class_list[i+1]
      list_len -= 1
      i -= 1
    i += 1
    while_cond = i < (list_len - 1)
  return class_list
###############################################################################



###############################################################################
# Функция, создающая ics-файл по сформированному списку занятий
###############################################################################
def create_ics_file(schedule, start_date, academic_hour_duration, short_recreation_duration, long_recreation_duration, file_name="schedule.ics", repeat_number = 4):
  # Преобразуем строку в дату
  start_date = datetime.strptime(start_date, '%d-%m-%Y')

  # Определяем день недели первого учебного дня (0 - понедельник, 6 - воскресенье)
  first_day_of_semester = start_date.weekday()

  # Создаем объект календаря
  cal = Calendar()

  # Определяем продолжительность пары
  pair_duration = academic_hour_duration * 2

  # Проходимся по всем записям расписания
  for entry in schedule:
    # Определяем продолжительность занятия
    class_duration = entry.duration * pair_duration + (entry.duration-1) * short_recreation_duration
    # Вычисляем смещение для первой недели с учетом дня недели начала семестра
    if (entry.week_day < first_day_of_semester) and (entry.week_code == 0):
      # Если целевой день недели 1-ой учебной недели идет до первого учебного
      # дня, переносим занятие на следующую итерацию "1-го числителя"
      week_offset = (entry.week_code + 4) * 7
      day_offset = entry.week_day - first_day_of_semester - 1
      first_class_date = start_date + timedelta(days=week_offset + day_offset)
    else:
      # Если целевой день недели идет во время или после дня недели первого
      # учебного дня или если это занятие не первой учебной недели
      week_offset = entry.week_code * 7
      day_offset = entry.week_day - first_day_of_semester
      first_class_date = start_date + timedelta(days=week_offset + day_offset)


    # Определяем время начала пары
    # Первая пара начинается в 9:00
    # Учитываем 10-минутные перемены между парами и 40 минут после второй пары
    start_time = first_class_date + timedelta(hours=9)  # Начало первой пары
    start_time += timedelta(minutes=entry.slot_number * (pair_duration + 10))  # Смещение для каждой пары

    # Учитываем, что перемена после второй пары составляет 40 минут
    if entry.slot_number > 2:
      start_time += timedelta(minutes=(long_recreation_duration - short_recreation_duration))

    # Продолжительность пары
    end_time = start_time + timedelta(minutes=class_duration)

    # Создаем событие
    event = Event()
    event.add('summary', entry.class_name)
    event.add('dtstart', start_time)
    event.add('dtend', end_time)
    event.add('location', entry.room_number)
    event.add('uid', str(uuid4()))

    # Устанавливаем правило повторения
    event.add('rrule', {'freq': 'weekly', 'interval': 4, 'count': repeat_number})

    # Добавляем событие в календарь
    cal.add_component(event)

  # Записываем календарь в файл
  with open(file_name, 'wb') as f:
    f.write(cal.to_ical())
###############################################################################



if educator_mode:
  unmerged_class_list = create_list_of_classes_by_educator(groups, educator, url, cookie)
else:
  unmerged_class_list = create_list_of_classes_by_student(group, url, cookie)
merged_class_list = merge_list_of_classes(unmerged_class_list)
create_ics_file(merged_class_list, semester_starts_at, academic_hour_duration, short_recreation_duration, long_recreation_duration, calendar_file_name, repeat_number)

