# Copyright 2016 Mycroft AI Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import time
from os.path import dirname, join
from datetime import datetime, timedelta
from mycroft import MycroftSkill, intent_file_handler
from mycroft.util.parse import extract_datetime, normalize, extract_duration
from mycroft.util.parse import extract_number
from mycroft.util.time import now_local
from mycroft.util.format import nice_time, nice_date, nice_duration, join_list, nice_date_time
from mycroft.util.log import LOG
from mycroft.util import play_wav
from mycroft.messagebus.client import MessageBusClient

REMINDER_PING = join(dirname(__file__), 'twoBeep.wav')

MINUTES = 60  # seconds

DEFAULT_TIME = now_local().replace(hour=8, minute=0, second=0)

def deserialize(dt):
    return datetime.strptime(dt, '%Y%d%m-%H%M%S-%z')


def serialize(dt):
    return dt.strftime('%Y%d%m-%H%M%S-%z')


def is_today(d):
    return d.date() == now_local().date()


def is_tomorrow(d):
    return d.date() == now_local().date() + timedelta(days=1)

class ReminderSkill(MycroftSkill):
    def __init__(self):
        super(ReminderSkill, self).__init__()
        self.primed = False

        self.cancelable = []  # list of reminders that can be cancelled
        self.NIGHT_HOURS = [23, 0, 1, 2, 3, 4, 5, 6]

    def initialize(self):
        # Handlers for notifications after speak
        # TODO Make this work better in test
        if isinstance(self.bus, MessageBusClient):
            self.bus.on('speak', self.prime)
            self.bus.on('mycroft.skill.handler.complete', self.notify)
            self.bus.on('mycroft.skill.handler.start', self.reset)

        # Reminder checker event
        self.schedule_repeating_event(self.__check_reminder, datetime.now(),
                                      0.5 * MINUTES, name='reminder')

    #def add_notification(self, identifier, note, expiry): # see #64
    #    self.notes[identifier] = (note, expiry)

    def is_affirmative(self, utterance):
        #affirmatives = ['yes', 'sure', 'please do']
        affirmatives = self.translate_list('Affirmatives')
        for word in affirmatives:
            if word in utterance:
                return True
        return False

    def prime(self, message):
        time.sleep(1)
        self.primed = True

    def reset(self, message):
        self.primed = False

    def contains_datetime(self, utterance):
        return extract_datetime(utterance, now_local(), self.lang) is not None

    def notify(self, message):
        time.sleep(10)
        if self.name in message.data.get('name', ''):
            self.primed = False
            return

        handled_reminders = []
        now = now_local()
        if self.primed:
            for r in self.settings.get('timed_reminders', []):                     ### 'timed_reminders'
                print('Checking {}'.format(r))
                dt = deserialize(r[1])
                notification = deserialize(r[2])
                if now > notification and now < dt and \
                        (r[0],r[1]) not in self.cancelable:
                    self.speak_dialog('ByTheWay', data={'reminder': r[0]})   ### 'timed_reminders'
                    #self.cancelable.append(r[0])
                    self.cancelable.append((r[0],r[1]))

            self.primed = False

    ################ keine Behandlung für unspec, because timed
    def __check_reminder(self, message):
        """ Repeating event handler. Checking if a reminder time has been
            reached and presents the reminder. """
        now = now_local()
        handled_reminders = []
        for r in self.settings.get('timed_reminders', []):
            self.log.info(r)
            dt = deserialize(r[1])
            if now > dt:
                play_wav(REMINDER_PING)
                self.speak_dialog('Reminding', data={'reminder': r[0]})   ### 'timed_reminders'
                handled_reminders.append(r)
            #if now > dt - timedelta(minutes=10):   # see #64
                #self.add_notification(r[0], r[0], dt)
        self.log.info("Check_reminder/handled: ")
        self.log.info(handled_reminders)
        self.remove_handled(handled_reminders)

    ################ keine Behandlung für unspec, because timed
    def remove_handled(self, handled_reminders):
        """ The reminder is removed and rescheduled to repeat in 2 minutes.

            It is also marked as "cancelable" allowing "cancel current
            reminder" to remove it.

            Repeats a maximum of 3 times.
        """
        for r in handled_reminders:
            #r[2] carries the pre notification time [dt]
            if type(r[2]) is int:
                repeats = r[2] + 1
            else:
                repeats = 1
            self.settings['timed_reminders'].remove(r)
            # If the reminer hasn't been repeated 3 times reschedule it
            if repeats < 3:
                self.log.info("Announcement No.:" + str(repeats))
                self.speak_dialog('ToCancelInstructions')
                new_time = deserialize(r[1]) + timedelta(minutes=2)
                new_time_serialized = serialize(new_time)
                self.settings['timed_reminders'].append(
                        (r[0], new_time_serialized, repeats))
                # Make the reminder cancelable
                for entry in self.cancelable:
                    if (r[0] in entry[0]) and (r[1] in entry[1]):
                        #remove bc it is deleted from cancelable (name/time indicator)
                        self.cancelable.remove(entry)
                        self.cancelable.append((r[0],new_time_serialized))
                        break
                else:
                    self.cancelable.append((r[0],new_time_serialized))
                self.log.info("cancelable list")
                self.log.info(self.cancelable)
            else:
                # Do not schedule a repeat and remove the reminder from
                # the list of cancelable reminders
                self.cancelable = [c for c in self.cancelable if c[0] != r[0]]

    def remove_by_name(self, name, time, reminder_list):
        for r in self.settings.get(reminder_list, []):
            if r[0] == name and r[1] == time:
                break
            else:
                return False  # No matching reminders found
        self.settings[reminder_list].remove(r)
        self.log.info(self.settings.get(reminder_list, []))
        return True  # Matching reminder was found and removed

    def check_duplicates(self, name, reminder_list, time=None, remove=False):
        duplicate_list = []
        for r in self.settings.get(reminder_list, []):
            self.log.info(r)
            self.log.info(r[0])
            self.log.info(name)
            # search for identical timestamps
            if time != None and (r[1] == time):
                self.log.warning("Time")
                break
            # search for identical reminder in terms of name in
            # timed reminder lists (see .cancelable) and untimed reminder lists
            elif (r[0] == name and isinstance(r, list)) or (r == name and isinstance(r, str)):
                self.log.warning("Text")
                duplicate_list.append(r)
        if len(duplicate_list) == 0:
            self.log.warning("False")
            return False, None  # No matching reminders found
        self.log.warning("remove")
        if remove:
            self.settings[reminder_list].remove(r)
        return True, duplicate_list  # Matching reminder were found (and removed if remove=true)

    ################ keine Behandlung für unspec, because timed
    def reschedule_by_name(self, name, time, new_time):
        """ Reschedule the reminder by it's name
            (and time ; to ensure more than one reminder "appointment" (or else)
            processed correctly)

            Arguments:
                name:       Name of reminder to reschedule.
                time:       Time of reminder to reschedule.
                new_time:   New time for the reminder.

            Returns (Bool): True if a reminder was found.
        """
        serialized = serialize(new_time)
        for r in self.settings.get('timed_reminders', []):                 ### 'timed_reminders'
            if r[0] == name and r[1] == time:
                break
        else:
            return False  # No matching reminders found
        self.settings['timed_reminders'].remove(r)
        self.settings['timed_reminders'].append((r[0], serialized))
        return True

    def date_str(self, d):
        if is_today(d):
            return 'today'
        elif is_tomorrow(d):
            return 'tomorrow'
        else:
            return nice_date(d.date(), self.lang, now_local())

    ################ keine Behandlung für unspec, because timed
    @intent_file_handler('ReminderAt.intent')
    def add_new_reminder(self, msg=None):
        """ Handler for adding  a reminder with a name at a specific time. """
        reminder = msg.data.get('reminder', None)
        if reminder is None:
            return self.add_unnamed_reminder_at(msg)

        # mogrify the response TODO: betterify!
        reminder = (' ' + reminder).replace(' my ', ' your ').strip()
        reminder = (' ' + reminder).replace(' our ', ' your ').strip()
        # time = msg.data.get('timedate', None) OR msg.data.get('date', None) ???
        utterance = msg.data['utterance']
        reminder_time, rest = (extract_datetime(utterance, now_local(),
                                                self.lang,
                                                default_time=DEFAULT_TIME) or
                               (None, None))

        if reminder_time.hour in self.NIGHT_HOURS:
            self.speak_dialog('ItIsNight')
            if not self.ask_yesno('AreYouSure') == 'yes':
                return  # Don't add if user cancels

        if reminder_time:  # A datetime was extracted
            self.__save_reminder_local(reminder, reminder_time)
        else:
            self.speak_dialog('NoDateTime')


    @intent_file_handler('Reminder.intent')
    def add_unspecified_reminder(self, msg=None):
        """ Starts a dialog to add a reminder when no time was supplied
            for the reminder.
        """
        reminder = msg.data['reminder']
        self.log.info(reminder)
        # Handle the case where padatious misses the time/date
        # Temporarily taken put due to lingua franca issue

        #if contains_datetime(msg.data['utterance']):
        #    return self.add_new_reminder(msg)

        response = self.get_response('ParticularTime')
        if self.is_affirmative(response) or self.contains_datetime(response):
        #if self.ask_yesno('ParticularTime') == 'yes':
            # Check if a time was also in the response
            self.log.info(response)
            dt, rest = (extract_datetime(response, now_local(), self.lang) or (None, None))
            while dt == None:
            #dt, rest = extract_datetime(response) or (None, None)
                response = self.get_response('SpecifyTime')
                #utterance = msg.data['utterance']
                dt, rest = (extract_datetime(response, now_local(), self.lang) or (None, None))
            #msg.data['reminder'] = reminder
            #msg.data['utterance'] = nice_date_time(dt, self.lang, now_local())
            #msg.data['date'] = nice_date(dt, self.lang, now_local())
            self.__save_reminder_local(reminder, dt)
        else:
            ### check if reminder allready exist in untimed_reminders List
            #for check_reminder in (self.settings.get('untimed_reminders', [])):
            #    self.log.warning(check_reminder)
            #    if (check_reminder == reminder):
            duplicate, _ = self.check_duplicates(reminder, "untimed_reminders")
            if duplicate:
                #response = self.get_response('Untimed_EntryAlreadyExit')
                #if response and self.is_affirmative(response):
                if self.is_affirmative(self.get_response('Untimed_EntryAlreadyExit')):
                    new_reminder = self.get_response('Specify')
                    #if self.is_affirmative(self.get_response('RemoveOld')):
                    #    self.remove_by_name(reminder, "untimed_reminders")
                    reminder = new_reminder
                else:
                    return

            LOG.debug('put into general reminders')
            self.__save_untimed_reminder(reminder)

    def __save_reminder_local(self, reminder, reminder_time):
        """ Speak verification and store the reminder. """
        """ Merged dialog SavingReminder, SavingReminderTomorrow, SavingReminderDate
            in SavingReminderDate
            Apllied to vocab en-us, other langs must adapt"""
        # Choose dialog depending on the date

        self.speak_dialog('SavingReminderDate',
                          {'time': nice_time(reminder_time, self.lang, now_local()),
                           'date': nice_date(reminder_time, self.lang, now_local())})

        def val_prenote_minutes(string):
            num = extract_number(string, self.lang)
            return num

        #How many minutes before event should be notified
        if self.ask_yesno('PreNotify') == 'yes':
            response = self.get_response('PreNotify_Minutes', validator=val_prenote_minutes)
            serialized_note = serialize(reminder_time - timedelta(minutes=int(response)))
        else:
            serialized_note = serialize(reminder_time)

        serialized_event = serialize(reminder_time)

        # Store reminder
        if 'timed_reminders' in self.settings:
            self.settings['timed_reminders'].append((reminder, serialized_event, serialized_note))   ### 'timed_reminders'
        else:
            self.settings['timed_reminders'] = [(reminder, serialized_event, serialized_note)]   ### erstelle Liste


    def __save_untimed_reminder(self, reminder):
        if 'untimed_reminders' in self.settings:
            self.settings['untimed_reminders'].append(reminder)
        else:
            self.settings['untimed_reminders'] = [reminder]


    ################ keine Behandlung für unspec, because timed
    @intent_file_handler('UnspecifiedReminderAt.intent')
    def add_unnamed_reminder_at(self, msg=None):
        """ Handles the case where a time was given but no reminder
            name was added.
        """
        utterance = msg.data['timedate']
        reminder_time, _ = (extract_datetime(utterance, now_local(), self.lang,
                                             default_time=DEFAULT_TIME) or
                            (None, None))

        response = self.get_response('AboutWhat')
        if response and reminder_time:
            self.__save_reminder_local(response, reminder_time)

    ################ keine Behandlung für unspec, because timed
    @intent_file_handler('DeleteReminderForDay.intent')
    def remove_reminders_for_day(self, msg=None):
        """ Remove all reminders for the specified date. """
        if 'date' in msg.data:
            date, _ = extract_datetime(msg.data['date'], lang=self.lang)
        else:
            date, _ = extract_datetime(msg.data['utterance'], lang=self.lang)

        date_str = self.date_str(date or now_local().date())
        # If no reminders exists for the provided date return;
        for r in self.settings['timed_reminders']:
            if deserialize(r[1]).date() == date.date():
                break
        else:  # Let user know that no reminders were removed
            self.speak_dialog('NoRemindersForDate', {'date': date_str})
            return

        answer = self.ask_yesno('ConfirmRemoveDay', data={'date': date_str})
        if answer == 'yes':
            if 'timed_reminders' in self.settings:
                self.settings['timed_reminders'] = [
                        r for r in self.settings['timed_reminders']
                        if deserialize(r[1]).date() != date.date()]

    @intent_file_handler('DeleteReminderPerName.intent')
    def delete_reminder_by_name(self, message):
        reminder = message.data.get('reminder', None)
        self.log.info(reminder)
        if self.ask_yesno('ClearEntry_WhichList') == 'yes':
            search_list="timed_reminders"
        else:
            search_list="untimed_reminders"
        dup_found, dup_list = self.check_duplicates(reminder, search_list)
        if dup_found:
            if len(dup_list) > 1:
                #voice out the reminder date of duplicates to be specific
                dt_list = []
                for dup in dup_list:
                    dt_list.append(nice_date(deserialize(dup[1]), self.lang, now_local()))
                date_str = join_list(dt_list, self.translate("and", self.lang))
                response = self.get_response('RemoveReminder_MultipleEntries',
                                data={'reminder': date_str})
                for reminder in dt_list:
                    if response in reminder[1]:
                        break
                remove_by_name(reminder, search_list)
            else:
                remove_by_name(reminder, search_list)
        else:
            self.speak_dialog('NoActive')

    ################ keine Behandlung für unspec, because timed
    @intent_file_handler('GetRemindersForDay.intent')
    def get_reminders_for_day(self, msg=None):
        """ List all reminders for the specified date. """
        if 'date' in msg.data:
            date, _ = extract_datetime(msg.data['date'], lang=self.lang)
        else:
            date, _ = extract_datetime(msg.data['utterance'], lang=self.lang)

        if 'timed_reminders' in self.settings:
            reminders = [r for r in self.settings['timed_reminders']
                         if deserialize(r[1]).date() == date.date()]
            if len(reminders) > 0:
                for r in reminders:
                    reminder, dt = (r[0], deserialize(r[1]))
                    self.speak(reminder + ' at ' + nice_time(dt))
                return
        self.speak_dialog('NoUpcoming')

    @intent_file_handler('GetNextReminders.intent')
    def get_next_reminder(self, msg=None):
        """ Get the first upcoming reminder. """
        if len(self.settings.get('timed_reminders', [])) > 0:
            reminders = [(r[0], deserialize(r[1]))
                         for r in self.settings['timed_reminders']]
            next_reminder = sorted(reminders, key=lambda tup: tup[1])[0]

            self.speak_dialog('NextOtherDate',
                              data={'time': nice_time(next_reminder[1], self.lang, now_local()),
                                    'date': nice_date(next_reminder[1], self.lang, now_local()),
                                    'reminder': next_reminder[0]})
            #if is_today(next_reminder[1]):
            #    self.speak_dialog('NextToday',
            #                      data={'time': nice_time(next_reminder[1], self.lang, now_local()),
            #                            'reminder': next_reminder[0]})
            #elif is_tomorrow(next_reminder[1]):
            #    self.speak_dialog('NextTomorrow',
            #                      data={'time': nice_time(next_reminder[1], self.lang, now_local()),
            #                            'reminder': next_reminder[0]})
            #else:
            #    self.speak_dialog('NextOtherDate',
            #                      data={'time': nice_time(next_reminder[1], self.lang, now_local()),
            #                            'date': nice_date(next_reminder[1], self.lang, now_local()),
            #                            'reminder': next_reminder[0]})
        else:
            self.speak_dialog('NoUpcoming')

    @intent_file_handler('GetUntimedReminder.intent')
    def get_untimed_reminder(self, msg=None):
        untimed_reminder_list = []
        """ Get Untimed Reminder and speak them in one go"""
        for reminder in (self.settings.get('untimed_reminders', [])):
            untimed_reminder_list.append(reminder)
        reminder_str = join_list(untimed_reminder_list, self.translate("and", self.lang))
        if reminder_str != '':
            self.speak_dialog('UntimedReminder', data={'reminder': reminder_str})
        else:
            self.speak_dialog('NoActive')

    def __cancel_active(self):
        """ Cancel all active reminders. """
        remove_list = []
        ret = len(self.cancelable) > 0  # there were reminders to cancel
        self.log.info(self.cancelable)
        for c in self.cancelable:
            if self.remove_by_name(c[0], c[1], "timed_reminders"):
                remove_list.append(c)
        for c in remove_list:
            self.cancelable.remove(c)
        self.log.info(self.cancelable)
        return ret

    @intent_file_handler('CancelActiveReminder.intent')
    def cancel_active(self, message):
        """ Cancel a reminder that's been triggered (and is repeating every
            2 minutes. """
        if self.__cancel_active():
            self.speak_dialog('ReminderCancelled')
        else:
            self.speak_dialog('NoActive')

    @intent_file_handler('SnoozeReminder.intent')
    def snooze_active(self, message):
        """ Snooze the triggered reminders with a delay of {delta} (default: 15 minutes). """
        remove_list = []
        utterance = message.data['utterance']
        delta, _ = extract_duration(utterance, self.lang) or (timedelta(minutes=15), None)
        for c in self.cancelable:
            if self.reschedule_by_name(c[0], c[1],
                                       now_local() + delta):
                #self.speak_dialog('RemindingInFifteen')
                self.speak_dialog('RemindingInFifteen',
                                  data={"time": nice_time(now_local() + delta , self.lang)})
                self.log.warning(now_local()+delta)
                remove_list.append(c)
        for c in remove_list:
            self.cancelable.remove(c)

    @intent_file_handler('ClearReminders.intent')
    def clear_all(self, message):
        """ Clear all reminders. """
        #### remove in favour of check_and_remove?
        if self.ask_yesno('ClearAll_WhichList') == 'yes':
            # remove from cancelable list
            self.__cancel_active()
            self.settings['timed_reminders'] = []
        else:
            self.settings['untimed_reminders'] = []
        self.speak_dialog('ClearedAll')

    def stop(self, message=None):
        if self.__cancel_active():
            self.speak_dialog('ReminderCancelled')
            return True
        else:
            return False

    def shutdown(self):
        if isinstance(self.bus, MessageBusClient):
            self.bus.remove('speak', self.prime)
            self.bus.remove('mycroft.skill.handler.complete', self.notify)
            self.bus.remove('mycroft.skill.handler.start', self.reset)


def create_skill():
    return ReminderSkill()
